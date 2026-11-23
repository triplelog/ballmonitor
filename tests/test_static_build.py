import json
import os
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ballmonitor.cli import main
from ballmonitor.core import registry, views
from ballmonitor.web import builder, server
from ballmonitor.web.builder import build_static_site, extract_entities

SITE_MODELS = [m for m in registry.model_names()
               if registry.config_for(m).status != "stub" and server.is_public(m)]
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
    monkeypatch.setattr(builder, "build_pages", lambda target, data_dir: [])


def test_extract_entities():
    entities = extract_entities()
    assert "pitchers" in entities and len(entities["pitchers"]) > 100
    assert "batters" in entities and len(entities["batters"]) > 100
    assert "college_teams" in entities and len(entities["college_teams"]) > 50
    assert "mlb_teams" in entities and len(entities["mlb_teams"]) == 30
    assert "races" in entities and len(entities["races"]) > 5


def test_build_static_site(site):
    # The public page is index.html; the editor is editor.html
    assert "/static/site.js" in (site / "index.html").read_text()
    assert "static/app.js" in (site / "editor.html").read_text()
    assert not (site / "game.html").exists()  # Pitch Guesser is off the site for now
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
    addresses = {m["name"] for m in index["models"]}
    assert {json.loads((site / "data" / "views" / f"{a}.json").read_text(encoding="utf-8"))["model"]
            for a in addresses} == set(WITH_PAGES)
    for a in addresses:
        page = builder.load_page(site / "data" / "views", a)   # split options' views read back
        assert views.check(page) == [], a
        assert (site / "data" / "views" / f"{a}.json").stat().st_size < 400_000, f"{a}: page data too big"
    # a big page's dropdown options load one at a time
    bowls = json.loads((site / "data" / "views" / "ncaaf_bowls.json").read_text(encoding="utf-8"))
    team = next(v for v in bowls["views"] if v["kind"] == "picker" and v["id"] == "team")
    georgia = next(o for o in team["options"] if o["slug"] == "georgia")
    assert georgia["views"] == [] and georgia["src"] == "/data/views/ncaaf_bowls/team/georgia.json"
    assert json.loads((site / georgia["src"].lstrip("/")).read_text(encoding="utf-8"))["views"]
    # every old address (a model's REDIRECTS) leads to a page that is on the site
    # (college_diamond's baseball/softball split is archived since 2026-11-20, so this may be empty)
    assert set(index["redirects"].values()) <= addresses


def test_every_address_is_a_real_page_in_the_sitemap(site):
    """Search engines see every page: a file per address, each with its own title, description and
    canonical link, all listed in sitemap.xml (pages built by web/pages.py)."""
    import re
    index = json.loads((site / "data" / "site.json").read_text(encoding="utf-8"))
    sitemap = re.findall(r"<loc>https://ballmonitor\.com(/[^<]*)</loc>", (site / "sitemap.xml").read_text())
    assert len(sitemap) == len(set(sitemap))
    expected = {"/", "/about/", "/privacy/", "/terms/", "/charts/", "/triple/", "/lineup/", "/27k/", "/hometurf/",
                "/ncaaf_bowls/team/georgia/", *(f"/{m['name']}/" for m in index["models"]),
                *(f"/tables/{t['id']}/" for t in index["tables"]), *(f"/charts/{c['id']}/" for c in index["charts"])}
    assert expected <= set(sitemap)
    titles = set()
    for path in sitemap:
        if path in builder.GAME_PATHS:
            continue
        text = (site / path.strip("/") / "index.html" if path != "/" else site / "index.html").read_text()
        title = re.search(r"<title>([^<]*)</title>", text).group(1)
        assert title not in titles, f"{path}: title {title!r} used twice"
        titles.add(title)
        assert f'<link rel="canonical" href="https://ballmonitor.com{path}">' in text, path
        assert f'<meta property="og:url" content="https://ballmonitor.com{path}">' in text, path
        assert re.search(r'<meta name="description" content="[^"]{20,}">', text), path
        assert re.search(r'src="/static/site\.js\?v=[0-9a-f]{10}"', text) and "{{" not in text, path  # cache-busted
    georgia = (site / "ncaaf_bowls" / "team" / "georgia" / "index.html").read_text()
    assert "<title>Georgia: " in georgia and 'class="intro"' not in georgia   # forecast pages: tables only
    # the words are in the page before any script runs; the text pages are left alone by site.js
    bowls = (site / "ncaaf_bowls" / "index.html").read_text()
    assert 'href="/ncaaf_bowls/team/georgia/"' in bowls and "How this works" in bowls
    assert re.search(r'id="app"[^>]* data-static', (site / "privacy" / "index.html").read_text())
    # the words written in the page sources (web/site/) are in the built pages, slots filled
    assert 'data-text="title"' in bowls and 'class="headline"' not in bowls and 'class="subtitle"' not in bowls
    recruiting = (site / "ncaaf_recruiting" / "index.html").read_text()
    newest = json.loads((site / "data" / "views" / "ncaaf_recruiting.json").read_text())["fill"]["last_year"]
    assert f'<span data-fill="last_year">{newest}</span>' in recruiting
    # a missing option's address (a past poll week) is forwarded to its page by the 404 page
    assert "/data/views/" in (site / "404.html").read_text() and "location.replace" in (site / "404.html").read_text()
    # an old address is a stub that forwards to the new one and isn't indexed
    for old_address, new in index["redirects"].items():
        if "/" in old_address:   # an old option address: forwarded by the 404 page, not a stub
            continue
        old = (site / old_address / "index.html").read_text()
        assert f"/{new}/" in old and 'content="noindex"' in old
        assert f"/{old_address}/" not in sitemap


def test_page_addresses_cannot_take_the_sites_own_folders(site, tmp_path):
    data = tmp_path / "data"
    (data / "views").mkdir(parents=True)
    page = {"title": "T", "summary": "S", "sport": "Running", "views": [], "updated": "", "order": 1}
    (data / "views" / "tables.json").write_text(json.dumps(page))
    (data / "site.json").write_text(json.dumps({"models": [{"name": "tables", **page}], "redirects": {},
                                                "tables": [], "charts": []}))
    with pytest.raises(ValueError, match="used by the site itself"):
        builder.build_pages(tmp_path, data)


def test_private_models_stay_off_the_site(site):
    hidden = [m for m in registry.model_names() if not server.is_public(m)]
    assert hidden, "expected some [web] public = false models"
    for m in hidden:
        assert not (site / "data" / "models" / f"{m}.json").exists(), m
        assert not (site / "data" / "views" / f"{m}.json").exists(), m


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
        for path in ("/triple/", "/data/site.json", "/static/site.js"):
            with urllib.request.urlopen(base_url + path) as res:
                assert res.status == 200, path
        with urllib.request.urlopen(f"{base_url}/data/manifest.json") as res:
            assert json.loads(res.read())["model_count"] == len(SITE_MODELS)
    finally:
        httpd.shutdown()


def test_cli_build_site(tmp_path, no_pages):
    target = tmp_path / "cli_dist"
    assert main(["build-site", "--out", str(target)]) == 0
    assert (target / "editor.html").exists() and (target / "404.html").exists()   # (pages: stubbed out)
    assert (target / "data" / "manifest.json").exists()


def test_cli_update_and_build(tmp_path, no_pages):
    target = tmp_path / "update_dist"
    assert main(["update-and-build", "--offline", "--models", "dad,race_podium", "--out", str(target)]) == 0
    assert (target / "editor.html").exists()
    assert (target / "data" / "manifest.json").exists()


def test_building_again_into_the_same_folder_works(site):
    """A second build into a folder that already holds a build (its chart pages included) must not
    mistake those pages for chart files the ids clash with."""
    assert (site / "charts").is_dir() and any((site / "charts" / d).is_dir() for d in ("aging-power", "power-average"))
    assert builder.build_pages(site, site / "data")


def test_off_site_models_leave_no_trace(site):
    """A model with [web] public = false (archived) has no page, no sitemap entry, no published app
    and no home/menu entry (the launch set, 2026-11-20)."""
    off = [m for m in registry.model_names() if not server.is_public(m)]
    assert {"race_time", "college_diamond", "ranked_choice", "progress_tracker", "lichess_rating",
            "running_progress", "strength_progress", "weight_loss"} <= set(off)
    index = json.loads((site / "data" / "site.json").read_text(encoding="utf-8"))
    shown = {json.loads((site / "data" / "views" / f"{m['name']}.json").read_text(encoding="utf-8"))["model"]
             for m in index["models"]}
    sitemap = (site / "sitemap.xml").read_text()
    for m in off:
        assert m not in shown, m
        assert f"/{m}/" not in sitemap, m
        assert not (site / "static" / "apps" / f"{m}.js").exists(), m
        assert f"apps/{m}.js" not in index["assets"], m


def test_rebuild_removes_pages_that_left_the_site(tmp_path):
    """Rebuilding into an old dist/ drops an archived model's page folder, an old forwarding stub and
    their page data, but keeps the site's own folders and anything written during this build."""
    import time
    old = time.time() - 60
    for name, html in {"gone": "<html>page</html>", "stub": '<meta name="robots" content="noindex">',
                       "about": "<html>about</html>"}.items():
        (tmp_path / name).mkdir()
        page = tmp_path / name / "index.html"
        page.write_text(html)
        os.utime(page, (old, old))
    (tmp_path / "sitemap.xml").write_text("<loc>https://ballmonitor.com/gone/</loc><loc>https://ballmonitor.com/about/</loc>")
    previous = builder._sitemap_folders(tmp_path)
    assert previous == {"gone", "about"}
    data = tmp_path / "data"
    (data / "views").mkdir(parents=True)
    (data / "site.json").write_text(json.dumps({"models": [{"name": "kept"}]}))
    for f in ("gone.json", "kept.json"):
        (data / "views" / f).write_text("{}")
        os.utime(data / "views" / f, (old, old))
    started = time.time()
    (tmp_path / "fresh").mkdir()
    (tmp_path / "fresh" / "index.html").write_text('<meta name="robots" content="noindex">')   # written now
    (tmp_path / "sitemap.xml").write_text("<loc>https://ballmonitor.com/about/</loc>")
    builder._remove_stale(tmp_path, data, previous, started, log=lambda *_: None)
    assert not (tmp_path / "gone").exists() and not (tmp_path / "stub").exists()
    assert (tmp_path / "about").exists() and (tmp_path / "fresh").exists()
    assert not (data / "views" / "gone.json").exists() and (data / "views" / "kept.json").exists()
