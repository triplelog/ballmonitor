import json
import threading
import tomllib
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ballmonitor.core import registry
from ballmonitor.web import server


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as res:
        return res.status, res.read().decode()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_index_and_assets_served(base_url):
    assert "ballmonitor" in get(base_url + "/")[1]
    assert get(base_url + "/static/app.js")[0] == 200
    assert get(base_url + "/static/style.css")[0] == 200
    # Direct model URLs serve the app
    assert "ballmonitor" in get(base_url + "/model/race_time")[1]
    assert "ballmonitor" in get(base_url + "/dad")[1]


def test_model_list_and_detail(base_url):
    models = json.loads(get(base_url + "/api/models")[1])
    assert {m["name"] for m in models} == set(registry.model_names())
    detail = json.loads(get(base_url + "/api/models/race_time?variant=trust_fit")[1])
    fit = next(p for p in detail["params"] if p["name"] == "fit_weight")
    assert fit["value"] == 0.95 and fit["default"] == 0.6
    assert "default" in detail["examples"]


def test_run_with_overrides(base_url):
    inputs = registry.model_dir("race_time").joinpath("examples/one_race.toml").read_text()
    status, body = post(base_url + "/api/models/race_time/run",
                        {"inputs_toml": inputs, "overrides": {"formulas.predict": "t * D / d"}})
    assert status == 200
    assert body["prediction"]["outcomes"][0]["estimate"] == pytest.approx(2400)
    assert "RESULT" in body["text"]


def test_bad_override_is_a_400_with_message(base_url):
    status, body = post(base_url + "/api/models/race_time/run", {"inputs_toml": "", "overrides": {"fit_weight": 5}})
    assert status == 400 and "outside its range" in body["error"]


def test_variant_toml_writer_round_trips():
    values = {"a": 0.5, "b": 3, "c": True, "d": "x \"quoted\" \\ path", "e": [0.1, 2]}
    text = "\n".join(f"{k} = {server._toml_value(v)}" for k, v in values.items())
    assert tomllib.loads(text) == values


def test_save_name_validation():
    with pytest.raises(ValueError):
        server._safe_name("../evil")


def test_pitch_guesser_game_endpoints(base_url):
    status, body = get(base_url + "/game")
    assert status == 200
    assert "Pitch Guesser" in body

    # Scenario endpoint
    status, sc_body = get(base_url + "/api/game/scenario?id=0")
    assert status == 200
    sc = json.loads(sc_body)
    assert sc["id"] == 0
    assert "pitcher" in sc
    assert "arsenal" in sc
    assert "ai_probs" in sc

    # Evaluation endpoint
    status, res = post(base_url + "/api/game/evaluate", {
        "id": 0,
        "player_probs": sc["ai_probs"]
    })
    assert status == 200
    assert res["result"] in ("win", "loss", "tie")
    assert "player_brier" in res
    assert "ai_brier" in res
    assert "actual" in res


def test_ui_has_element_for_every_id_app_js_writes():
    # app.js once wrote to a missing #markdown-rendered and every model page crashed.
    import re
    static = registry.MODELS_DIR.parent / "web" / "static"
    html = (static / "index.html").read_text()
    js = (static / "app.js").read_text()
    ids = set(re.findall(r'id="([\w-]+)"', html))
    for used in set(re.findall(r'\$\("#([\w-]+)"\)\.(?:textContent|innerHTML|value|disabled)\s*=', js)):
        assert used in ids, f"app.js writes to #{used}, which index.html does not define"
    for tab in re.findall(r'showTab\("(\w+)"\)', js):
        assert f'data-panel="{tab}"' in html, f"showTab('{tab}') has no panel"


def test_server_does_not_serve_files_outside_the_app(base_url):
    # The live UI must not pick up a stale dist/ bundle (it forced static mode) or escape via '..'.
    for path in ("/data/manifest.json", "/data/../pyproject.toml", "/static/../server.py"):
        with pytest.raises(urllib.error.HTTPError) as err:
            get(base_url + path)
        assert err.value.code == 404


def test_entities_endpoint(base_url):
    data = json.loads(get(base_url + "/data/entities.json")[1])
    assert len(data["mlb_teams"]) == 30 and data["pitchers"]


def test_web_section_hides_examples_and_params():
    # config.toml [web] hides research-only pieces from the site; the CLI still has them.
    detail = server.model_detail("ncaaf_recruiting")
    assert "mbb_2025" not in detail["examples"] and "default" in detail["examples"]
    assert not any(p["name"].startswith("bball_") for p in detail["params"])
    assert "mbb_2025" in registry.example_names("ncaaf_recruiting")


def test_27k_game_is_served(base_url):
    if not server.GAME_27K.is_dir():
        pytest.skip("27K build not present")
    status, body = get(base_url + "/27k/")
    assert status == 200 and "27K" in body
    assert get(base_url + "/27k/css/style.css")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base_url + "/27k/../server.py")
    assert err.value.code == 404


def test_triple_play_is_served(base_url):
    status, body = get(base_url + "/triple/")
    assert status == 200 and "Triple Play" in body
    assert get(base_url + "/triple/game.js")[0] == 200
    assert get(base_url + "/triple/puzzles/daily/index.json")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as err:
        get(base_url + "/triple/../build.py")
    assert err.value.code == 404


def test_export_replay_writes_mp4(tmp_path):
    # Full video export: needs the optional `video` extra (Playwright + a browser) and ffmpeg.
    import shutil
    pytest.importorskip("playwright")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    from ballmonitor.web.export_replay import export
    out = export("401858275", tmp_path / "r.mp4", {"duration_sec": 6}, fps=10, log=lambda *_: None)
    assert out.stat().st_size > 10_000
