import json
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ballmonitor.cli import main
from ballmonitor.core import registry

SITE_MODELS = [m for m in registry.model_names() if registry.config_for(m).status != "stub"]
from ballmonitor.web.builder import build_static_site, extract_entities


def test_extract_entities():
    entities = extract_entities()
    assert "pitchers" in entities and len(entities["pitchers"]) > 100
    assert "batters" in entities and len(entities["batters"]) > 100
    assert "college_teams" in entities and len(entities["college_teams"]) > 50
    assert "mlb_teams" in entities and len(entities["mlb_teams"]) == 30
    assert "races" in entities and len(entities["races"]) > 5


def test_build_static_site(tmp_path):
    out = build_static_site(tmp_path)
    assert out == tmp_path

    # Core HTML/JS/CSS assets
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "game.html").exists()
    assert (tmp_path / "static" / "app.js").exists()
    assert (tmp_path / "static" / "style.css").exists()

    # Data files
    manifest_file = tmp_path / "data" / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["static_mode"] is True
    assert set(manifest["models"]) == set(SITE_MODELS)

    entities_file = tmp_path / "data" / "entities.json"
    assert entities_file.exists()
    entities = json.loads(entities_file.read_text(encoding="utf-8"))
    assert len(entities["pitchers"]) > 0

    models_file = tmp_path / "data" / "models.json"
    assert models_file.exists()
    models = json.loads(models_file.read_text(encoding="utf-8"))
    assert len(models) == len(SITE_MODELS)

    # Check each model has detail and precomputed examples
    for m in SITE_MODELS:
        detail_file = tmp_path / "data" / "models" / f"{m}.json"
        assert detail_file.exists(), f"missing {detail_file}"
        ex_dir = tmp_path / "data" / "models" / m / "examples"
        assert ex_dir.exists()
        def_ex = ex_dir / "default.json"
        assert def_ex.exists(), f"missing default example for {m}"
        ex_data = json.loads(def_ex.read_text(encoding="utf-8"))
        assert "prediction" in ex_data
        assert "text" in ex_data
        assert "markdown" in ex_data


def test_static_server_serves_bundle(tmp_path):
    build_static_site(tmp_path)

    class CustomHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path), **kwargs)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), CustomHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

    try:
        with urllib.request.urlopen(f"{base_url}/index.html") as res:
            assert res.status == 200
            content = res.read().decode("utf-8")
            assert "ballmonitor" in content
            assert 'data-tab="backtest"' not in content  # Backtest tab removed

        with urllib.request.urlopen(f"{base_url}/game.html") as res:
            assert res.status == 200

        with urllib.request.urlopen(f"{base_url}/data/manifest.json") as res:
            assert res.status == 200
            data = json.loads(res.read())
            assert data["model_count"] == len(SITE_MODELS)

        with urllib.request.urlopen(f"{base_url}/data/entities.json") as res:
            assert res.status == 200
            data = json.loads(res.read())
            assert "pitchers" in data
    finally:
        httpd.shutdown()


def test_cli_build_site(tmp_path):
    target = tmp_path / "cli_dist"
    code = main(["build-site", "--out", str(target)])
    assert code == 0
    assert (target / "index.html").exists()
    assert (target / "data" / "manifest.json").exists()


def test_cli_update_and_build(tmp_path):
    target = tmp_path / "update_dist"
    code = main(["update-and-build", "--offline", "--models", "dad,race_podium", "--out", str(target)])
    assert code == 0
    assert (target / "index.html").exists()
    assert (target / "data" / "manifest.json").exists()
