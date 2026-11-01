import datetime

import pytest

from ballmonitor.core import formula, registry
from ballmonitor.core.config import parse_value
from ballmonitor.core.params import ConfigError
from ballmonitor.core.units import format_time, parse_distance, parse_time


# ── formulas ────────────────────────────────────────────────────────────────

def test_formula_arithmetic_and_functions():
    assert formula.evaluate("t * (D / d) ** k", {"t": 10, "D": 4, "d": 2, "k": 1}) == 20
    assert formula.evaluate("max(a, 3) if a > 0 else -1", {"a": 5}) == 5
    assert formula.evaluate("logistic(0)", {}) == 0.5


@pytest.mark.parametrize("expr", [
    "__import__('os')",
    "x.__class__",
    "open('f')",
    "[1, 2]",
    "'text'",
    "lambda: 1",
])
def test_formula_rejects_unsafe_syntax(expr):
    with pytest.raises(formula.FormulaError):
        formula.check(expr, {"x"})
    with pytest.raises(formula.FormulaError):
        formula.evaluate(expr, {"x": 1})


def test_formula_check_catches_typos():
    with pytest.raises(formula.FormulaError, match="unknown name 'kk'"):
        formula.check("t * kk", {"t", "k"})


# ── config layering ─────────────────────────────────────────────────────────

def test_parse_value_uses_toml_syntax():
    assert parse_value("0.8") == 0.8
    assert parse_value("true") is True
    assert parse_value("[1, 2]") == [1, 2]
    assert parse_value("nearest") == "nearest"


def test_override_marks_param_and_keeps_default():
    cfg = registry.config_for("race_time", overrides={"fit_weight": 0.9})
    spec = cfg.params.specs["fit_weight"]
    assert spec.value == 0.9 and spec.default == 0.6 and spec.overridden


def test_variant_then_override_order():
    cfg = registry.config_for("race_time", "trust_fit", {"fit_weight": 0.7})
    assert cfg.params.fit_weight == 0.7
    assert cfg.variant == "trust_fit"


def test_out_of_range_override_rejected():
    with pytest.raises(ConfigError, match="outside its range"):
        registry.config_for("race_time", overrides={"fit_weight": 1.5})


def test_unknown_param_rejected():
    with pytest.raises(ConfigError, match="unknown parameter"):
        registry.config_for("race_time", overrides={"fit_wieght": 0.5})


def test_wrong_type_rejected():
    with pytest.raises(ConfigError, match="expects float"):
        registry.config_for("race_time", overrides={"fit_weight": "high"})


def test_bad_formula_override_rejected_at_load():
    with pytest.raises(ConfigError, match="unknown name"):
        registry.config_for("race_time", overrides={"formulas.predict": "t * (D / d) ** kk"})


def test_stub_models_refuse_to_run(monkeypatch):
    cfg = registry.config_for("race_time")
    cfg.status = "stub"
    monkeypatch.setattr(registry, "load_config", lambda *a, **kw: cfg)
    with pytest.raises(registry.ModelNotReady):
        registry.load_model("race_time")


def test_fetch_due_follows_config_season(monkeypatch):
    d = datetime.date

    def due(fetch_table, day, name="ncaaf_bowls"):
        cfg = registry.config_for(name)
        cfg.extra["fetch"] = fetch_table
        monkeypatch.setattr(registry, "config_for", lambda *a, **kw: cfg)
        return registry.fetch_due(name, today=d(*day))[0]

    wraps = {"auto": True, "season": ["08-15", "01-25"]}
    assert due(wraps, (2026, 10, 31)) and due(wraps, (2027, 1, 25)) and due(wraps, (2026, 8, 15))
    assert not due(wraps, (2027, 1, 26)) and not due(wraps, (2026, 6, 1))
    spring = {"auto": True, "season": ["03-20", "11-05"]}
    assert due(spring, (2026, 7, 4)) and not due(spring, (2026, 12, 1))
    assert due({"auto": True}, (2026, 6, 1))
    assert not due({}, (2026, 10, 31)) and not due({"auto": False, "season": ["01-01", "12-31"]}, (2026, 6, 1))


def test_models_without_fetch_py_are_never_due():
    assert registry.fetch_due("race_time") == (False, "no fetch.py")


# ── units ───────────────────────────────────────────────────────────────────

def test_time_round_trip():
    assert parse_time("1:32:00") == 5520
    assert format_time(5520) == "1:32:00"
    assert format_time(1200) == "20:00"


def test_distance_parsing():
    assert parse_distance("Half") == 21097.5
    assert parse_distance("10 mi") == pytest.approx(16093.44)
    assert parse_distance("3000m") == 3000
    assert parse_distance(400) == 400


# ── public-site pages (core/views.py) ──────────────────────────────────────────

def test_views_check_accepts_a_well_formed_page():
    from ballmonitor.core import views as V
    t = V.table("t", "Teams", [V.col("team", "Team"), V.col("p", "Chance", "pct", bar=True)],
                [{"team": "A", "p": 0.4}, {"team": "B", "p": None}], search=True, page_size=1, sort="p")
    b = V.bar("b", "Bars", [{"label": "A", "value": 0.4}])
    ln = V.line("l", "Line", [V.series("A", [(0, 1), (1, 2)], band=[(0, 0.5, 1.5)])], x_fmt="time")
    pk = V.picker("p", "Pick", "Team", [V.option("A", [t]), V.option("B", [b])])
    p = V.clean(V.page("Title", "Summary.", "Running", [t, b, ln, pk]))
    assert V.check(p) == []


def test_views_check_reports_problems():
    from ballmonitor.core import views as V
    bad = V.page("T", "S", "Curling", [
        V.table("t", "T", [V.col("a", "A", "percent")], [{"b": 1}], sort="zzz"),
        V.bar("t", "Dup id", [{"label": "x"}]),
        V.line("l", "L", [V.series("s", [])]),
        V.picker("p", "P", "X", []),
    ])
    errs = " | ".join(V.check(bad))
    for expect in ("sport must be", "fmt 'percent'", "missing ['a']", "sort key", "duplicate id",
                   "numeric value", "needs points", "no options"):
        assert expect in errs, expect
    assert any("JSON" in e for e in V.check(V.page("T", "S", "Running", [V.bar("b", "B", [{"label": "x", "value": float("nan")}])])))
    assert V.check(V.clean(V.page("T", "S", "Running", [V.bar("b", "B", [{"label": "x", "value": 1.0}])]))) == []
