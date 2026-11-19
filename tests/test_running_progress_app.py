"""The running log tool on the public page (web/static/apps/running_progress.js) must give the
same forecast as the running_progress model: it is a JavaScript copy of model.py, run in the
visitor's browser on the log they keep there. Runs the script under node with the page's own
data (site.log_data) and compares it with model.predict on real and edge-case logs; also checks
the file imports (Strava, Garmin, generic CSV, the tool's own JSON/CSV). The CSV snippets below
are synthetic, written in each app's export format; they are not anyone's data."""

import csv
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.models.running_progress import features, site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "running_progress.js"
NODE = shutil.which("node")
NAME = "running_progress"
KEYS = ("pace", "km", "p_running", "tanda_now", "tanda_target", "pace_now", "km_now", "share")


def _node(script: str):
    run = subprocess.run([NODE, "-e", f"const app = require({json.dumps(str(APP))});\n{script}"],
                         capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def _entries_from_example(name: str) -> tuple[list[dict], str]:
    ex = registry.load_example(NAME, name)
    out = []
    for e in ex["log"]:
        out.append({"date": features.as_date(e["date"]).isoformat(), "km": features.entry_km(e),
                    "minutes": features.entry_minutes(e)})
    return out, ex


def _weekly_to_entries(today: dt.date, km: list[float], minutes: list[float]) -> list[dict]:
    """Weekly totals (oldest first, last = the week before today) as one dated entry per week."""
    n = len(km)
    return [{"date": (today - dt.timedelta(days=7 * (n - 1 - i) + 1 + (i % 7))).isoformat(), "km": k, "minutes": m}
            for i, (k, m) in enumerate(zip(km, minutes))]


def _cases() -> list[dict]:
    cases = []
    for name, weeks in (("default", 13), ("patchy_rebuilder", 8)):
        entries, ex = _entries_from_example(name)
        cases.append({"entries": entries, "today": features.as_date(ex["today"]).isoformat(), "weeks_ahead": weeks,
                      "southern": False})
    entries, ex = _entries_from_example("placeholder_daily_miles")
    cases.append({"entries": entries, "today": features.as_date(ex["today"]).isoformat(),
                  "target": features.as_date(ex["target_date"]).isoformat(), "southern": False})
    rows = list(csv.DictReader(open(registry.model_dir(NAME) / "data" / "backtest.csv")))
    picked = rows[:12] + [r for r in rows if r["hemisphere"] == "south"][:4] + [r for r in rows if r["split"] == "covid"][:4]
    for r in picked:
        today = dt.date.fromisoformat(r["today"])
        km = [float(x) for x in r["weekly_km"].split()]
        mins = [float(x) for x in r["weekly_minutes"].split()]
        cases.append({"entries": _weekly_to_entries(today, km, mins), "today": r["today"],
                      "weeks_ahead": float(r["weeks_ahead"]), "southern": r["hemisphere"] == "south"})
    today = dt.date(2026, 6, 1)
    steady_km, steady_min = [30.0] * 20, [165.0] * 20
    edge = [
        ([30.0] * 6, [165.0] * 6, 4),                                       # short log (6 weeks)
        (steady_km[:-1] + [250.0], steady_min[:-1] + [20.0], 26),           # implausible last week
        ([40.0] * 14 + [0.0] * 4, [220.0] * 14 + [0.0] * 4, 9),             # no run in the last 4 weeks
        ([0.0, 25.0, 0.0, 0.0, 30.0, 0.0, 12.0, 0.0, 0.0, 18.0, 0.0, 0.0],
         [0.0, 150.0, 0.0, 0.0, 170.0, 0.0, 80.0, 0.0, 0.0, 100.0, 0.0, 0.0], 17),   # patchy
    ]
    for km, mins, weeks in edge:
        cases.append({"entries": _weekly_to_entries(today, km, mins), "today": today.isoformat(),
                      "weeks_ahead": weeks, "southern": False})
    # entries on/after today and older than the lookback are ignored; a target 13.4 weeks away
    entries = _weekly_to_entries(today, steady_km, steady_min) + [
        {"date": today.isoformat(), "km": 99.0, "minutes": 500.0},
        {"date": (today - dt.timedelta(days=400)).isoformat(), "km": 10.0, "minutes": 60.0}]
    cases.append({"entries": entries, "today": today.isoformat(),
                  "target": (today + dt.timedelta(days=94)).isoformat(), "southern": True})
    return cases


def _python(model, case: dict) -> dict:
    inputs = {"today": case["today"], "log": case["entries"], "hemisphere": "south" if case["southern"] else "north"}
    if "target" in case:
        inputs["target_date"] = case["target"]
    else:
        inputs["weeks_ahead"] = case["weeks_ahead"]
    pred = model.predict(inputs)
    x = pred.extras
    return {"pace": x["pace_quantiles"], "km": x["km_quantiles"], "p_running": x["p_running"],
            "tanda_now": x["tanda_now"], "tanda_target": x["tanda_target"],
            "pace_now": pred.outcome("Average pace now").estimate,
            "km_now": pred.outcome("Weekly km now").estimate, "share": x["features"]["share"]}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_log_tool_matches_the_model():
    model = registry.load_model(NAME)
    data = site.log_data(model)
    cases = _cases()
    out = _node(f"const data = {json.dumps(data)};\nconst cases = {json.dumps(cases)};\n"
                "console.log(JSON.stringify(cases.map((c) => app.compute(data, c))));")
    for case, got in zip(cases, out):
        assert "error" not in got, (case["today"], got)
        want = _python(model, case)
        for key in KEYS:
            assert got[key] == pytest.approx(want[key], rel=1e-9, abs=1e-9), (key, case["today"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_log_tool_refuses_what_the_model_refuses():
    model = registry.load_model(NAME)
    data = site.log_data(model)
    today = dt.date(2026, 6, 1)
    too_little = {"entries": _weekly_to_entries(today, [0.0] * 10 + [10.0, 10.0], [0.0] * 10 + [60.0, 60.0]),
                  "today": today.isoformat(), "weeks_ahead": 8, "southern": False}
    ok = {"entries": _weekly_to_entries(today, [30.0] * 12, [165.0] * 12), "today": today.isoformat(), "southern": False}
    cases = [too_little, {**ok, "weeks_ahead": 3}, {**ok, "weeks_ahead": 27}, {**ok, "entries": []}]
    out = _node(f"const data = {json.dumps(data)};\nconst cases = {json.dumps(cases)};\n"
                "console.log(JSON.stringify(cases.map((c) => app.compute(data, c).error || null)))")
    assert all(out), out
    for case in cases[:3]:
        with pytest.raises(ValueError):
            _python(model, case)


STRAVA = (
    "Activity ID,Activity Date,Activity Name,Activity Type,Activity Description,Elapsed Time,Distance,"
    "Max Heart Rate,Relative Effort,Commute,Activity Private Note,Activity Gear,Filename,Athlete Weight,"
    "Bike Weight,Elapsed Time,Moving Time,Distance,Max Speed\n"
    '101,"Mar 3, 2026, 6:10:00 AM",Morning Run,Run,"Easy, with ""strides""\nsecond line",3300,10.02,,,false,,,'
    "activities/101.fit,,,3300.0,3150.0,10020.0,4.1\n"
    '102,"Mar 4, 2026, 5:00:00 PM",Commute,Ride,,1800,8.5,,,true,,,,,,1800.0,1700.0,8500.0,9.0\n'
    '103,"Mar 6, 2026, 7:00:00 AM",Trail,Trail Run,,4000,"12,5",,,false,,,,,,4000.0,3900.0,,3.9\n'
    '104,"Mar 7, 2026, 7:00:00 AM",Broken,Run,,,,,,false,,,,,,,,,\n'
)
GARMIN = (
    "Activity Type,Date,Favorite,Title,Distance,Calories,Time,Avg HR,Max HR,Avg Pace,Moving Time,Elapsed Time\n"
    "Running,2026-03-03 06:10:00,false,Easy,6.21,600,00:52:30,140,160,8:27,00:52:00,00:53:00\n"
    "Cycling,2026-03-04 17:00:00,false,Ride,20.0,500,01:00:00,120,150,--,01:00:00,01:00:00\n"
    "Treadmill Running,2026-03-05 18:00:00,false,Intervals,4.00,400,00:31:12.5,150,175,7:48,00:31:00,00:33:00\n"
)
GENERIC = "date,distance,duration,note\n2026-03-03,10,52:30,easy\n2026-03-05,8.5,45,\nnot a date,5,30:00,\n"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_imports_and_exports():
    km_mi = features.KM_PER_MILE
    script = (
        f"const K = {km_mi};\n"
        f"const strava = app.importCSV(app.parseCSV({json.dumps(STRAVA)}), 'km', K);\n"
        f"const garmin = app.importCSV(app.parseCSV({json.dumps(GARMIN)}), 'mi', K);\n"
        f"const generic = app.importCSV(app.parseCSV({json.dumps(GENERIC)}), 'km', K);\n"
        "const csvBack = app.importCSV(app.parseCSV(app.exportCSV(strava.entries)), 'mi', K);\n"
        "const json = app.importJSON(JSON.stringify({model: 'running_progress', version: 1, settings: {units: 'mi'},"
        " entries: [...generic.entries, {date: '2026-02-30', km: 5, minutes: 30}, {date: '2026-03-01', km: -1, minutes: 3}]}));\n"
        "const other = app.importJSON(JSON.stringify({model: 'weight_loss', entries: []}));\n"
        "const merged = app.mergeEntries(strava.entries, [...strava.entries, ...garmin.entries]);\n"
        "console.log(JSON.stringify({strava, garmin, generic, csvBack, json, other: other.errors,"
        " merged: merged.added, n: merged.entries.length, bad: app.importJSON('{oops').errors,"
        " dates: ['Jan 5, 2024, 6:30:12 AM', '2024-01-05 06:30:12', '5 Jan 2024', '2024-02-30', 'soon'].map(app.parseDate),"
        " nums: ['10.5', '10,5', '1,234.5', 'abc', ''].map(app.parseNumber)}));"
    )
    out = _node(script)
    s = out["strava"]
    assert s["kind"] == "strava" and s["notRuns"] == 1 and s["skipped"] == 1
    assert [e["date"] for e in s["entries"]] == ["2026-03-03", "2026-03-06"]
    assert s["entries"][0]["km"] == pytest.approx(10.02) and s["entries"][0]["minutes"] == pytest.approx(52.5)
    assert s["entries"][1]["km"] == pytest.approx(12.5)              # first Distance column, decimal comma
    assert s["entries"][0]["note"] == "Morning Run"                  # the quoted, multi-line description parsed
    g = out["garmin"]
    assert g["kind"] == "garmin" and g["notRuns"] == 1 and len(g["entries"]) == 2
    assert g["entries"][0]["km"] == pytest.approx(round(6.21 * km_mi, 3))
    assert g["entries"][1]["minutes"] == pytest.approx(31.21, abs=0.01)
    gen = out["generic"]
    assert gen["kind"] == "generic" and len(gen["entries"]) == 2 and gen["skipped"] == 1
    assert gen["entries"][1]["minutes"] == 45
    assert out["csvBack"]["entries"] == s["entries"]                 # own CSV export reads back unchanged
    j = out["json"]
    assert len(j["entries"]) == 2 and j["skipped"] == 2 and j["settings"] == {"units": "mi"}
    assert out["other"] and out["bad"]
    assert out["merged"] == 2 and out["n"] == 4                      # duplicates are not added twice
    assert out["dates"] == ["2024-01-05", "2024-01-05", "2024-01-05", None, None]
    assert out["nums"] == [10.5, 10.5, 1234.5, None, None]


def test_log_tool_is_on_the_page_and_valid():
    page = site.page(registry.load_model(NAME))
    tool = next(v for v in page["views"] if v["kind"] == "app")
    assert tool["app"] == NAME and views.check(views.clean(page)) == []
    data = tool["data"]
    assert data["storage_key"] == "bm.log.running_progress.v1"
    assert len(data["pace_z"]) == 7 and len(data["season_km"]) == 12 and len(data["example"]["weeks"]) == 26
    assert "fetch(" not in APP.read_text() and "XMLHttpRequest" not in APP.read_text()   # nothing is uploaded
