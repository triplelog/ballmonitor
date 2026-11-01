import json
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ballmonitor.cli import main
from ballmonitor.core import registry, views
from ballmonitor.web import builder
from ballmonitor.web.builder import build_static_site, extract_entities

SITE_MODELS = [m for m in registry.model_names() if registry.config_for(m).status != "stub"]
WITH_PAGES = [m for m in SITE_MODELS if (registry.model_dir(m) / "site.py").exists()]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """One full build (every example and every public page) shared by the tests below."""
    out = tmp_path_factory.mktemp("site")
    assert build_static_site(out, log=lambda *_: None) == out
    return out


@pytest.fixture
def no_pages(monkeypatch):
    """CLI tests check the command wiring only; the pages are covered by `site`."""
    monkeypatch.setattr(builder, "build_views", lambda data_dir, names, log=print: [])


def test_extract_entities():
    entities = extract_entities()
    assert "pitchers" in entities and len(entities["pitchers"]) > 100
    assert "batters" in entities and len(entities["batters"]) > 100
    assert "college_teams" in entities and len(entities["college_teams"]) > 50
    assert "mlb_teams" in entities and len(entities["mlb_teams"]) == 30
    assert "races" in entities and len(entities["races"]) > 5


def test_build_static_site(site):
    # The public page is index.html; the editor is editor.html
    assert "static/site.js" in (site / "index.html").read_text()
    assert "static/app.js" in (site / "editor.html").read_text()
    assert (site / "game.html").exists()
    for name in ("app.js", "style.css", "site.js", "site.css"):
        assert (site / "static" / name).exists()

    manifest = json.loads((site / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["static_mode"] is True
    assert set(manifest["models"]) == set(SITE_MODELS)

    entities = json.loads((site / "data" / "entities.json").read_text(encoding="utf-8"))
    assert len(entities["pitchers"]) > 0

    models = json.loads((site / "data" / "models.json").read_text(encoding="utf-8"))
    assert len(models) == len(SITE_MODELS)

    # Each model has detail and precomputed examples (the editor's data)
    for m in SITE_MODELS:
        assert (site / "data" / "models" / f"{m}.json").exists(), m
        ex = json.loads((site / "data" / "models" / m / "examples" / "default.json").read_text(encoding="utf-8"))
        assert {"prediction", "text", "markdown"} <= set(ex)


def test_public_pages_are_built_and_valid(site):
    index = json.loads((site / "data" / "site.json").read_text(encoding="utf-8"))
    assert {m["name"] for m in index["models"]} == set(WITH_PAGES)
    for m in WITH_PAGES:
        page = json.loads((site / "data" / "views" / f"{m}.json").read_text(encoding="utf-8"))
        assert views.check(page) == [], m


def test_static_server_serves_bundle(site):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base_url}/index.html") as res:
            assert res.status == 200 and "Ball Monitor" in res.read().decode("utf-8")
        with urllib.request.urlopen(f"{base_url}/editor.html") as res:
            content = res.read().decode("utf-8")
            assert "ballmonitor" in content
            assert 'data-tab="backtest"' not in content  # Backtest tab removed
        for path in ("/game.html", "/data/site.json", "/static/site.js"):
            with urllib.request.urlopen(base_url + path) as res:
                assert res.status == 200, path
        with urllib.request.urlopen(f"{base_url}/data/manifest.json") as res:
            assert json.loads(res.read())["model_count"] == len(SITE_MODELS)
    finally:
        httpd.shutdown()


def test_cli_build_site(tmp_path, no_pages):
    target = tmp_path / "cli_dist"
    assert main(["build-site", "--out", str(target)]) == 0
    assert (target / "index.html").exists() and (target / "editor.html").exists()
    assert (target / "data" / "manifest.json").exists()


def test_cli_update_and_build(tmp_path, no_pages):
    target = tmp_path / "update_dist"
    assert main(["update-and-build", "--offline", "--models", "dad,race_podium", "--out", str(target)]) == 0
    assert (target / "index.html").exists()
    assert (target / "data" / "manifest.json").exists()
