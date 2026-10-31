import pytest

from ballmonitor.core import registry


def run(inputs, variant=None, **overrides):
    return registry.load_model("_template", variant, overrides).predict(inputs)


def test_midpoint_is_coin_flip():
    pred = run({"score": 50}, midpoint=50.0)
    assert pred.primary.probability == pytest.approx(0.5)


def test_probabilities_sum_to_one():
    pred = run({"score": 73})
    assert sum(o.probability for o in pred.outcomes) == pytest.approx(1.0)
