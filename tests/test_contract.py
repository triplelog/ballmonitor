"""Rules every model must follow. New models are picked up automatically.

These enforce the project's promises: everything documented, every output in the
same shape, every example runnable.
"""

import datetime
import json

import pytest

from ballmonitor.core import registry
from ballmonitor.core.prediction import FORMATS
from ballmonitor.core.render import render

ALL = registry.model_names()
RUNNABLE = [n for n in ALL if registry.config_for(n).status != "stub"]
EXAMPLES = [(n, e) for n in RUNNABLE for e in registry.example_names(n)]


@pytest.mark.parametrize("name", ALL)
def test_model_is_documented(name):
    cfg = registry.config_for(name)
    directory = registry.model_dir(name)
    assert (directory / "MODEL.md").exists(), "every model needs MODEL.md"
    assert (directory / "model.py").exists()
    assert cfg.question, "meta.question is required"
    assert cfg.assumptions, "meta.assumptions must list at least one assumption"
    for spec in cfg.params.specs.values():
        assert spec.description, f"param '{spec.name}' needs a description"
    for f in cfg.params.formulas.values():
        assert f.description, f"formula '{f.name}' needs a description"


@pytest.mark.parametrize("name", ALL)
def test_fetch_policy_is_well_formed(name):
    policy = registry.config_for(name).extra.get("fetch")
    if policy is None:
        return
    assert (registry.model_dir(name) / "fetch.py").exists(), "[fetch] needs a fetch.py"
    assert set(policy) <= {"auto", "season"}, f"unknown [fetch] keys: {set(policy) - {'auto', 'season'}}"
    assert isinstance(policy.get("auto", False), bool)
    if "season" in policy:
        season = policy["season"]
        assert len(season) == 2, 'season = ["MM-DD", "MM-DD"]'
        for s in season:
            datetime.date(2000, *(int(x) for x in s.split("-")))  # valid month-day (2000: leap year)
    registry.fetch_due(name)


@pytest.mark.parametrize("name", RUNNABLE)
def test_runnable_model_has_default_example(name):
    assert "default" in registry.example_names(name), "add examples/default.toml"


@pytest.mark.parametrize("name", RUNNABLE)
def test_variants_load(name):
    for variant in registry.variant_names(name):
        registry.load_model(name, variant)


@pytest.mark.parametrize("name,example", EXAMPLES)
def test_example_produces_standard_prediction(name, example):
    pred = registry.load_model(name).predict(registry.load_example(name, example))
    assert pred.outcomes, "a prediction needs at least one outcome"
    assert pred.steps, "record calculation steps so the output shows its work"
    for o in pred.outcomes:
        assert o.fmt in FORMATS
        assert o.estimate is not None or o.probability is not None
        if o.probability is not None:
            assert 0.0 <= o.probability <= 1.0
        if o.interval is not None:
            assert pred.interval_level is not None, "set interval_level when reporting ranges"
            assert o.interval[0] <= o.interval[1]

    text = render(pred, "text")
    for heading in ("INPUTS", "RESULT", "HOW IT WAS COMPUTED", "PARAMETERS", "KEY ASSUMPTIONS"):
        assert heading in text
    too_wide = [line for line in text.splitlines() if len(line) > 78]
    assert not too_wide, f"text report must fit 78 columns: {too_wide[0]!r}"
    json.loads(render(pred, "json"))
    assert "### Result" in render(pred, "md")
