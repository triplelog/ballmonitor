"""Pieces of the public page's script (web/static/site.js) run under node: table sorting, and
the static checks for the front-end fixes (menu closing, picker focus, jump bar, Columns menu)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "ballmonitor" / "web" / "static"
SITE_JS = (STATIC / "site.js").read_text()
NODE = shutil.which("node")


def _sorting_code() -> str:
    """site.js's record parsing and value comparison, cut out so node can run them alone."""
    start = SITE_JS.index("const RECORD =")
    end = SITE_JS.index("function renderTable(")
    return SITE_JS[start:end]


def _sort(values: list, desc: bool = False) -> list:
    js = _sorting_code() + f"""
const vals = {json.dumps(values)};
const dir = {"-1" if desc else "1"};
console.log(JSON.stringify([...vals].sort((a, b) => compareValues(a, b) * dir)));
console.log(JSON.stringify(recordColumn(vals.map((v) => ({{ k: v }})), "k")));
"""
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout.split("\n")
    return json.loads(out[0]), json.loads(out[1])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_records_sort_by_win_share_then_wins():
    got, is_record = _sort(["9-1", "10-0", "1-9", "10-2", "5-5", "6-6", "7-2-1"], desc=True)
    assert got == ["10-0", "9-1", "10-2", "7-2-1", "6-6", "5-5", "1-9"]
    assert is_record


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_text_and_dates_still_sort_as_text():
    got, is_record = _sort(["Georgia", "Alabama", "Utah"])
    assert got == ["Alabama", "Georgia", "Utah"] and not is_record
    got, is_record = _sort(["2026-11-20", "2026-09-01", "2025-12-31"])
    assert got == ["2025-12-31", "2026-09-01", "2026-11-20"] and not is_record


def test_focus_after_link_targets_the_addressed_picker():
    body = SITE_JS[SITE_JS.index("function focusAfter("):]
    assert "#v-${CSS.escape(p[1])} select" in body[:800]
    assert 'querySelector(".view-picker select")' not in SITE_JS


def test_menu_closes_on_links_added_later():
    shioh = (STATIC / "shioh.js").read_text()
    # delegated on the menu cell, not bound per link at load (site.js adds #nav-models later)
    assert re.search(r"cell\.addEventListener\('click'.*?closest\('\.ss-nav a'\)", shioh, re.S)
    assert "querySelectorAll('.ss-nav a').forEach" not in shioh


def test_jump_bar_and_columns_menu_and_back():
    assert "function jumpBar(" in SITE_JS and "views.length < 4" in SITE_JS
    assert re.search(r'"jump-bar".*?viewSrc\(`\$\{v\.id\}\.title`\)', SITE_JS, re.S)   # data-src on each link
    assert 'details.col-chooser[open]' in SITE_JS and '"Escape"' in SITE_JS
    assert "function samePage(" in SITE_JS and "HOME_DESCRIPTION" not in SITE_JS


def test_bracket_quick_filters_links_and_try_buttons():
    # the bracket is drawn with the same markup web/pages.py writes (bracket_html)
    body = SITE_JS[SITE_JS.index("function renderBracket("):]
    for cls in ('"bracket"', '"bk-round"', '"bk-round-name"', '"bk-games"', '"bk-game"', '"bk-where"', '"bk-champ"',
                '"bk-seed"', '"bk-name"', '"bk-p"', 'bk-team${won ? " won" : ""}'):
        assert cls in body[:2500], cls
    assert 'case "bracket": return viewShell(v, renderBracket(v)' in SITE_JS
    # links only go to picker options that exist; list cells link each part
    assert "function optionHref(" in SITE_JS and "current.slugs" in SITE_JS and "function linkedParts(" in SITE_JS
    # quick filters and Try presets are toggle buttons
    assert '"quick-filters"' in SITE_JS and SITE_JS.count('"aria-pressed"') >= 2
    assert "v.y_reverse" in SITE_JS
    # charts: reset, download and the first-load note, done from outside pyslots' form
    for text in ("Reset formulas", "Download PNG", "Loading Python for your first chart"):
        assert text in SITE_JS, text


def test_charts_wait_for_the_visitor_before_loading_python():
    # pyslots' embed runs its first chart as soon as it is mounted (even with autoRun: false), so the
    # charts page mounts it only after "Draw the chart", or at once for a visitor who drew one before
    body = SITE_JS[SITE_JS.index("async function renderCharts("):]
    body = body[:body.index("\n}\n")]
    assert '"Draw the chart"' in body and "drewBefore()" in body and "if (atOnce) await draw();" in body
    assert body.index("loadPyslots()") > body.index("const draw = async")   # the embed loads only inside draw()
    assert body.count("loadPyslots()") == 1
