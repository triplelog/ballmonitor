"""The page sources in web/site/ (web/pages.py) and the preview server that shows them."""
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ballmonitor.web import pages, preview

SOURCES = pages.source_files()


def test_every_page_has_a_source():
    names = {f.parent.relative_to(pages.SITE_DIR).as_posix() for f in SOURCES}
    assert {".", "charts", "tables", *pages.TEXT_PAGES} <= names
    assert (pages.SITE_DIR / "404.html").is_file()


@pytest.mark.parametrize("source", SOURCES, ids=lambda f: f.parent.name or "home")
def test_page_source_is_a_whole_page(source):
    text = source.read_text(encoding="utf-8")
    assert set(pages.shared_blocks(text)) == set(pages.SHARED), "keep the shell:* blocks (copy them from index.html)"
    assert re.search(r'<main class="ss-main" id="app" data-page="[^"]*"', text), "<main> needs id=app and data-page"
    assert '<script src="/static/site.js"></script>' in text
    for pattern in (r"<title>[^<]*</title>", r'<meta name="description" content="[^"]+">',
                    r'<link rel="canonical" href="[^"]*">', r'<meta property="og:url" content="[^"]*">'):
        assert re.search(pattern, text), pattern
    # the address in data-page is the file's own (site.js swaps pages by it)
    key = re.search(r'data-page="([^"]*)"', text).group(1)
    assert key == source.parent.relative_to(pages.SITE_DIR).as_posix().replace(".", ""), key


def test_source_file_serves_options_charts_and_tables():
    assert pages.source_file("/") == pages.address_file("")
    assert pages.source_file("/ncaaf_bowls/team/georgia/") == pages.address_file("ncaaf_bowls")
    assert pages.source_file("/charts/aging-power/") == pages.address_file("charts")
    assert pages.source_file("/tables/qb-games/") == pages.address_file("tables")
    assert pages.source_file("/about/index.html") == pages.address_file("about")
    assert pages.source_file("/no_such_page/") is None
    assert pages.source_file("/../static/") is None


def test_sync_copies_the_home_pages_shell(tmp_path, monkeypatch):
    for f in (pages.address_file(""), pages.address_file("about")):
        dest = tmp_path / f.relative_to(pages.SITE_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(pages, "SITE_DIR", tmp_path)
    home = tmp_path / "index.html"
    home.write_text(home.read_text(encoding="utf-8").replace("<!-- /shell:footer -->", "NEW<!-- /shell:footer -->"),
                    encoding="utf-8")
    assert pages.sync() == [tmp_path / "about" / "index.html"]
    assert "NEW<!-- /shell:footer -->" in (tmp_path / "about" / "index.html").read_text(encoding="utf-8")
    assert pages.sync() == []


@pytest.fixture
def preview_server(tmp_path):
    """The preview server with no build yet (only pages and /static are asked for here)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), preview.handler(preview.Preview(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_preview_serves_the_sources(preview_server):
    page = urllib.request.urlopen(f"{preview_server}/ncaaf_bowls/team/georgia/").read().decode()
    assert 'data-page="ncaaf_bowls"' in page and 'data-slot="views"' in page
    css = urllib.request.urlopen(f"{preview_server}/static/site.css").read().decode()
    assert ".slot" in css
    assert urllib.request.urlopen(f"{preview_server}/favicon.svg").headers["content-type"] == "image/svg+xml"
