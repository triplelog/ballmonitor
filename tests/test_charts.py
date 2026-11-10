"""The baseball charts (ballmonitor/charts, copied from pyslots by scripts/sync-charts.sh): every
listed template is there with the data it reads, the form's script and styles are there, and the
build copies them to dist/charts/."""

import json
import re

from ballmonitor.web import server

CHARTS = server.CHARTS


def test_every_listed_chart_and_its_data_are_there():
    charts = json.loads((CHARTS / "examples" / "index.json").read_text())
    assert charts and all(c["file"].startswith("charts/") and c["title"] for c in charts)
    for c in charts:
        template = CHARTS / "examples" / c["file"]
        text = template.read_text()
        data = re.search(r"^# mathzetta-data: (.+)$", text, re.M)
        assert data, f"{c['file']}: no data line"
        assert (template.parent / data.group(1).strip()).resolve().is_file(), f"{c['file']}: no {data.group(1)}"
        for slot in ("title", "x_label", "y_label"):   # the page's title and axis-name boxes
            assert f"# mathzetta: {slot}() = " in text, f"{c['file']}: no {slot} slot"


def test_the_form_is_there():
    assert (CHARTS / "embed" / "pyslots-embed.js").stat().st_size > 50_000
    assert (CHARTS / "embed" / "inlinemath" / "inlinemath.css").is_file()
    assert (CHARTS / "examples" / "data" / "README.md").is_file()   # the data's licence


def test_build_copies_the_charts():
    from pathlib import Path
    from ballmonitor.web import builder
    assert 'shutil.copytree(server.CHARTS, target / "charts"' in Path(builder.__file__).read_text()
