"""Live data tables (web/tables.toml): config rules, which tables reach the site, the server check."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ballmonitor.web import tables


def test_config_is_valid():
    cfg = tables.load()
    assert cfg["table"], "tables.toml lists no tables"
    assert tables.validate(cfg) == []


def test_tables_without_a_server_address_stay_off_the_site():
    cfg = tables.load()
    cfg["servers"] = {k: "" for k in cfg["servers"]}
    assert tables.public(cfg) == []


def test_public_tables_carry_the_full_address_and_starting_view():
    cfg = tables.load()
    cfg["servers"] = {k: "https://tables.example.org/" for k in cfg["servers"]}
    live = tables.public(cfg)
    assert len(live) == len(cfg["table"])
    bat = next(t for t in live if t["id"] == "batting-games")
    assert bat["server"] == "https://tables.example.org/batting/" and bat["backend"] == "tabc"
    assert bat["options"]["filter"] and bat["options"]["sort"]["column"] == "date"
    assert all(ex["label"] for ex in bat["examples"])


@pytest.mark.parametrize("change, message", [
    (lambda c: c["table"][0].update(backend="duckdb"), "backend"),
    (lambda c: c["table"][0].update(path="batting"), "path must end"),
    (lambda c: c["table"][0].update(server="nowhere"), "not in [servers]"),
    (lambda c: c["table"][1].update(id=c["table"][0]["id"]), "id used twice"),
    (lambda c: c["servers"].update(retrosheet="tables.example.org"), "address must"),
])
def test_validate_catches_mistakes(change, message):
    cfg = tables.load()
    change(cfg)
    assert any(message in e for e in tables.validate(cfg))


@pytest.fixture
def fake_tabc():
    """A stand-in tabc server: /batting/columns.json answers, /pitching/ doesn't exist."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/batting/columns.json":
                body = json.dumps({"nrows": 3, "columns": [{"name": n} for n in
                                   ("date", "player", "team", "opp", "ab", "r", "h", "d", "t", "hr", "rbi", "w", "k", "sb")]})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def test_check_reports_answers_missing_columns_and_dead_tables(fake_tabc):
    cfg = tables.load()
    cfg["servers"]["retrosheet"] = fake_tabc
    res = {tid: (ok, msg) for tid, ok, msg in tables.check(cfg, timeout=3)}
    ok, msg = res["batting-games"]
    assert not ok and "not on the server" in msg            # the column key names columns the fake lacks
    assert "14 columns" in msg
    assert res["pitching-games"][0] is False                 # 404


def test_sqldn_meta_column_names():
    meta = {"tables": [{"name": "People", "columns": [{"name": "nameFirst"}]},
                       {"name": "Batting", "columns": [{"name": "HR"}]}]}
    assert tables.column_names(meta, "Batting") == {"HR"}
    assert tables.column_names(meta) == {"nameFirst", "HR"}
