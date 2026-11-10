"""The baseball charts page's list (web/charts.toml): every chart's template is there, every
formula fills one of that template's slots, and the build writes the list into data/site.json."""

import pytest

from ballmonitor.web import charts


def test_chart_list_is_valid():
    cfg = charts.load()
    assert len(cfg["chart"]) >= 7
    assert charts.validate(cfg) == []
    # every template the charts page offers is used at least once
    import json
    listed = {c["file"] for c in json.loads((charts.TEMPLATES / "index.json").read_text())}
    assert listed <= {c["template"] for c in cfg["chart"]}


@pytest.mark.parametrize("change, message", [
    (lambda c: c["chart"][0].update(template="charts/nope.py"), "not in charts/examples/index.json"),
    (lambda c: c["chart"][0].setdefault("formulas", {}).update(colour="year"), "not a slot"),
    (lambda c: c["chart"][1].update(id=c["chart"][0]["id"]), "id used twice"),
    (lambda c: c["chart"][0].update(id="Bad Id"), "lowercase"),
    (lambda c: c["chart"][0].pop("intro"), "needs intro"),
])
def test_validate_catches_mistakes(change, message):
    cfg = charts.load()
    change(cfg)
    assert any(message in e for e in charts.validate(cfg))


def test_text_slots_are_quoted():
    """Titles and axis names are text: MathZetta needs them in quotes, or it reads them as maths."""
    for c in charts.load()["chart"]:
        for k in ("title", "x_label", "y_label"):
            v = c.get("formulas", {}).get(k)
            if v is not None:
                assert v.startswith('"') and v.endswith('"'), (c["id"], k, v)


def test_public_list_carries_what_the_page_needs():
    out = charts.public()
    assert out and all({"id", "group", "title", "intro", "template", "formulas"} <= set(c) for c in out)
