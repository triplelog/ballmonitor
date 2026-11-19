"""The Lichess rating log on the public page (web/static/apps/lichess_rating.js) must give the same
numbers as the lichess_rating model: it is a JavaScript copy of model.py + dist.py (features, the
keeps-playing logistic, the quantile regression and the mixture with exponential tails), run in the
visitor's browser. Runs the script under node with the page's own data (site.py) and compares
with model.predict, plus the log's import/export helpers and the Lichess games summary."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.core import registry, views
from ballmonitor.models.lichess_rating import site

APP = Path(__file__).resolve().parent.parent / "ballmonitor" / "web" / "static" / "apps" / "lichess_rating.js"
NODE = shutil.which("node")
SHOWN = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)

# model.py input names -> the app's
NAMES = {"rating": "rating", "horizon_days": "horizon", "games_total": "games_total", "games_last_28_days": "games_28",
         "games_last_91_days": "games_91", "days_since_last_game": "days_since", "peak_rating": "peak",
         "rating_91_days_ago": "rating_91", "score_last_91_days": "score_91",
         "opponents_avg_last_91_days": "opp_avg", "keep_playing": "keep_playing", "goal_rating": "goal"}

BASE = {"rating": 1650, "horizon_days": 182, "games_total": 900, "games_last_28_days": 60,
        "games_last_91_days": 170, "days_since_last_game": 1, "peak_rating": 1720, "rating_91_days_ago": 1610,
        "score_last_91_days": 90, "opponents_avg_last_91_days": 1640, "goal_rating": 1800}
CASES = [
    BASE,
    {"rating": 1380, "horizon_days": 91, "games_total": 40, "games_last_28_days": 40},           # defaults
    {**BASE, "horizon_days": 30, "goal_rating": 1600},                                          # goal below today
    {**BASE, "games_last_28_days": 0, "games_last_91_days": 6, "days_since_last_game": 60,
     "keep_playing": True, "rating": 1900, "games_total": 4000, "peak_rating": 2010,
     "score_last_91_days": 2.5, "rating_91_days_ago": 1910, "opponents_avg_last_91_days": 1905},
    {**BASE, "games_last_28_days": 0, "games_last_91_days": 0, "days_since_last_game": 400,
     "score_last_91_days": 0, "horizon_days": 365},                                               # stopped long ago
    {**BASE, "rating": 2600, "games_total": 60000, "peak_rating": 3100, "rating_91_days_ago": 2000,
     "score_last_91_days": 170, "horizon_days": 1},                                              # beyond every cap
    {**BASE, "rating": 400, "peak_rating": 400, "rating_91_days_ago": 900, "score_last_91_days": 0,
     "opponents_avg_last_91_days": 1500, "horizon_days": 1000},
    {**BASE, "rating": 1700, "goal_rating": 1700},                                              # on a milestone
]


def _python(model, case):
    pred = model.predict(case)
    x = pred.extras
    out = {"p_active": x["p_active"], "q": [x["quantiles"][t] for t in SHOWN],
           "change": list(x["change_if_playing"]), "features": x["features"]}
    probs = {o.label: o.probability for o in pred.outcomes if o.probability is not None}
    out["p_higher"] = probs["Higher than today"]
    out["milestones"] = [v for k, v in probs.items() if k.startswith("Reaches")]
    out["goal"] = next((v for k, v in probs.items() if k.startswith("At or above goal")), None)
    return out


def _node(script: str):
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def _js(data, cases):
    js_cases = [{NAMES[k]: v for k, v in c.items()} for c in cases]
    script = (f"const app = require({json.dumps(str(APP))});\n"
              f"const data = {json.dumps(data)};\n"
              f"const cases = {json.dumps(js_cases)};\n"
              "console.log(JSON.stringify(cases.map((c) => { const r = app.predict(data, c);"
              " return {p_active: r.p_active, q: [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975].map((t) => r.quantiles[t]),"
              " change: r.change_if_playing, features: r.features, p_higher: r.p_higher,"
              " milestones: r.milestones.map((m) => m.p), goal: r.goal ? r.goal.p : null}; })));")
    return _node(script)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("overrides", [None, {"band_scale": 1.6, "milestone_step": 50, "cap_trend": 1.0}])
def test_app_matches_the_model(overrides):
    model = registry.load_model("lichess_rating", overrides=overrides)
    data = site.calculator_data(model)
    for case, got in zip(CASES, _js(data, CASES)):
        want = _python(model, case)
        assert got["p_active"] == pytest.approx(want["p_active"], abs=1e-9), case
        assert got["q"] == pytest.approx(want["q"], abs=1e-6), case
        assert got["change"] == pytest.approx(want["change"], abs=1e-6), case
        for k, v in want["features"].items():
            assert got["features"][k] == pytest.approx(v, abs=1e-9), (case, k)
        assert got["p_higher"] == pytest.approx(want["p_higher"], abs=1e-9)
        assert got["milestones"] == pytest.approx(want["milestones"], abs=1e-9)
        if want["goal"] is None:
            assert got["goal"] is None
        else:
            assert got["goal"] == pytest.approx(want["goal"], abs=1e-9)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_app_rejects_what_the_model_rejects():
    model = registry.load_model("lichess_rating")
    data = site.calculator_data(model)
    bad = [{**BASE, "games_last_91_days": 10, "games_last_28_days": 20},
           {**BASE, "score_last_91_days": 500},
           {**BASE, "rating": 300},
           {k: v for k, v in BASE.items() if k != "days_since_last_game"} | {"games_last_28_days": 0},
           {**BASE, "horizon_days": 0}]
    for case in bad:
        with pytest.raises(ValueError):
            model.predict(case)
    js_cases = [{NAMES[k]: v for k, v in c.items()} for c in bad]
    script = (f"const app = require({json.dumps(str(APP))});\nconst data = {json.dumps(data)};\n"
              f"console.log(JSON.stringify({json.dumps(js_cases)}.map((c) => {{ try {{ app.predict(data, c); return null; }}"
              " catch (e) { return e.message; } })));")
    assert all(_node(script)), "every bad case must give an error message"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_log_import_export_and_lichess_summary():
    data = site.calculator_data(registry.load_model("lichess_rating"))
    day = 86400000
    now = 1_800_000_000_000
    me = {"user": {"id": "someone"}}
    games = [  # newest first, like the Lichess export
        {"rated": True, "status": "mate", "createdAt": now - 2 * day, "lastMoveAt": now - 2 * day + 300000, "winner": "white",
         "players": {"white": {**me, "rating": 1660}, "black": {"user": {"id": "a"}, "rating": 1700}}},
        {"rated": True, "status": "draw", "createdAt": now - 20 * day,
         "players": {"white": {"user": {"id": "b"}, "rating": 1600}, "black": {"user": {"id": "SomeOne"}, "rating": 1650}}},
        {"rated": True, "status": "aborted", "createdAt": now - 30 * day,
         "players": {"white": {**me, "rating": 1640}, "black": {"user": {"id": "c"}, "rating": 1500}}},
        {"rated": True, "status": "resign", "createdAt": now - 80 * day, "winner": "black",
         "players": {"white": {**me, "rating": 1620}, "black": {"user": {"id": "d"}, "rating": 1630}}},
    ]
    csv_text = ('date,speed,rating,games,note\n2026-01-05,blitz,1600,800,"first, with comma"\n'
                '2026-02-30,blitz,1610,810,\n2026-03-01,Bullet,1500,,\n2026-03-02,hyper,1500,1,\n')
    json_text = json.dumps({"model": "lichess_rating", "version": 1, "settings": {"speed": "rapid", "goal": 1800,
                            "stats": {"blitz": {"games_28": 5, "peak": "x"}}, "saved": [{"bad": 1}]},
                            "entries": [{"date": "2026-04-01", "speed": "blitz", "rating": 1620, "games": 900, "note": ""},
                                        {"date": "2026-04-01", "speed": "blitz", "rating": 99}]})
    script = (f"const app = require({json.dumps(str(APP))});\nconst data = {json.dumps(data)};\n"
              f"const s = app.summarizeGames({json.dumps(games)}, 'someone', {now}, 1700);\n"
              f"const c = app.parseImport({json.dumps(csv_text)}, data);\n"
              f"const j = app.parseImport({json.dumps(json_text)}, data);\n"
              "let other = null; try { app.parseImport(JSON.stringify({model: 'weight_loss', entries: []}), data); } catch (e) { other = e.message; }\n"
              "const merged = app.mergeEntries(c.entries, [{date: '2026-01-05', speed: 'blitz', rating: 1605, games: 801, note: ''}]);\n"
              "const csv = app.toCsv([{date: '2026-01-05', speed: 'blitz', rating: 1600, games: null, note: '=cmd()'}]);\n"
              "console.log(JSON.stringify({s, c, j, other, merged, csv, round: app.parseImport(app.toCsv(c.entries), data).entries}));")
    out = _node(script)
    s = out["s"]
    assert s["games_91"] == 3 and s["games_28"] == 2          # the aborted game doesn't count
    assert s["score_91"] == 1.5                               # win + draw + loss
    assert s["opp_avg"] == pytest.approx((1700 + 1600 + 1630) / 3, abs=0.05)
    assert s["days_since"] == 1                               # last move 2 days minus 5 minutes ago
    assert s["rating_91"] == 1620                             # pre-game rating of the oldest game
    c = out["c"]
    assert [e["date"] for e in c["entries"]] == ["2026-01-05", "2026-03-01"]
    assert c["entries"][0]["note"] == "first, with comma" and c["entries"][1] == {
        "date": "2026-03-01", "speed": "bullet", "rating": 1500, "games": None, "note": ""}
    assert len(c["errors"]) == 2 and "line 3" in c["errors"][0]
    j = out["j"]
    assert len(j["entries"]) == 1 and len(j["errors"]) == 1
    assert j["settings"]["speed"] == "rapid" and j["settings"]["stats"]["blitz"] == {"games_28": 5}
    assert j["settings"]["saved"] == []
    assert out["other"] and "different tool" in out["other"]
    assert len(out["merged"]) == 2 and out["merged"][0]["rating"] == 1605
    assert out["csv"].splitlines() == ["date,speed,rating,games,note", "2026-01-05,blitz,1600,,'=cmd()"]
    assert out["round"] == c["entries"]


def test_app_view_is_on_the_page_and_valid():
    page = site.page(registry.load_model("lichess_rating"))
    assert views.check(views.clean(page)) == []
    tool = next(v for v in page["views"] if v["kind"] == "app")
    assert tool["app"] == "lichess_rating" and tool["data"]["storage_key"] == "bm.log.lichess_rating.v1"
    assert len(tool["data"]["change"]) == 7 and all(len(c) == 8 for c in tool["data"]["change"])
    assert page["views"][0] is tool and page["headline"]


def test_app_refuses_a_changed_formula():
    model = registry.load_model("lichess_rating", overrides={"formulas.p_active": "logistic(active_intercept)"})
    with pytest.raises(ValueError):
        site.calculator_data(model)
