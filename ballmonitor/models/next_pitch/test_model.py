"""next_pitch tests: hand-calculated cases on a tiny synthetic pitcher, plus checks on real data."""

import csv
import gzip
import json
import math

import pytest

from ballmonitor.core import registry
from ballmonitor.models.next_pitch.model import NextPitchModel
from ballmonitor.models.next_pitch.pitches import K, VOCAB, count_after, load_history, parse_sequence

UNIFORM = [1.0 / K] * K
COLS = ["date", "game_pk", "ab", "pn", "balls", "strikes", "stand", "pt", "res", "outs", "runners", "tto", "batter"]


def synthetic(tmp_path, pitches, prior=UNIFORM):
    """A model directory with one pitcher (id 1, 'Test Pitcher'). pitches: (date, balls, strikes, stand, type, res)."""
    data = tmp_path / "data"
    (data / "pitchers").mkdir(parents=True)
    with open(data / "pitchers.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([["pitcher_id", "name", "throws", "total"], [1, "Test Pitcher", "R", len(pitches)]])
    with gzip.open(data / "pitchers" / "1.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for i, (d, b, s, stand, t, r) in enumerate(pitches):
            w.writerow([d, 100, i, 1, b, s, stand, t, r, 0, 0, 1, 9])  # each pitch its own at-bat
    (data / "meta.json").write_text(json.dumps({"last_date": "2026-09-30", "league_prior": {"R": prior, "L": prior}}))
    load_history.cache_clear()
    return tmp_path


def model_for(directory, **overrides):
    cfg = registry.config_for("next_pitch", None, {"method": "tree", **overrides})
    return NextPitchModel(cfg, directory)


def prob(pred, code):
    return pred.extras["probs"][code]


# ── parsing ──────────────────────────────────────────────────────────────────

def test_sequence_parsing_and_implied_count():
    seq = parse_sequence("FF:C sl:ball FF:foul FF:F")
    assert seq == [("FF", "C"), ("SL", "B"), ("FF", "F"), ("FF", "F")]
    assert count_after(seq) == (1, 2)  # a foul with two strikes does not add a strike
    assert parse_sequence(["FA:swinging_strike"]) == [("FF", "S")]  # FA folds into FF
    with pytest.raises(ValueError):
        count_after(parse_sequence("FF:B FF:B FF:B FF:B"))
    with pytest.raises(ValueError):
        parse_sequence("XX:B")


# ── hand-calculated tree ─────────────────────────────────────────────────────

PITCHES = (
    [("2026-09-01", 0, 0, "R", "FF", "B")] * 6
    + [("2026-09-01", 0, 0, "R", "SL", "B")] * 2
    + [("2026-09-01", 0, 2, "R", "SL", "S")] * 3
    + [("2026-09-01", 0, 2, "R", "FF", "S")] * 1
)


def test_no_shrinkage_gives_raw_count_frequencies(tmp_path):
    m = model_for(synthetic(tmp_path, PITCHES), chain=["count"], half_life_days=0.0,
                  strength_overall=0.0, strength_count=0.0)
    pred = m.predict({"pitcher": "Test Pitcher", "stand": "R", "balls": 0, "strikes": 2})
    assert prob(pred, "SL") == pytest.approx(3 / 4)
    assert prob(pred, "FF") == pytest.approx(1 / 4)
    first = m.predict({"pitcher": "1", "stand": "R"})  # id lookup, 0-0 default
    assert prob(first, "FF") == pytest.approx(6 / 8)


def test_shrinkage_matches_formula(tmp_path):
    # overall: (FF 7, SL 5) of 12 with 2 pseudo-pitches of a uniform prior; count 0-2: (FF 1, SL 3) with strength 4
    m = model_for(synthetic(tmp_path, PITCHES), chain=["count"], half_life_days=0.0,
                  strength_overall=2.0, strength_count=4.0)
    pred = m.predict({"pitcher": "Test Pitcher", "stand": "R", "balls": 0, "strikes": 2})
    overall_sl = (5 + 2 / K) / 14
    assert prob(pred, "SL") == pytest.approx((3 + 4 * overall_sl) / (4 + 4))
    assert sum(pred.extras["probs"].values()) == pytest.approx(1.0, abs=1e-5)
    assert prob(pred, "KN") > 0  # never-seen pitch keeps a little probability


def test_recency_half_life_halves_old_pitches(tmp_path):
    pitches = [("2026-09-20", 0, 0, "R", "FF", "B"), ("2026-09-30", 0, 0, "R", "SL", "B")]
    m = model_for(synthetic(tmp_path, pitches), chain=["count"], half_life_days=10.0,
                  strength_overall=0.0, strength_count=0.0)
    pred = m.predict({"pitcher": "Test Pitcher", "stand": "R", "as_of": "2026-10-10"})
    # SL is 10 days old (weight 1/2), FF is 20 days old (weight 1/4)
    assert prob(pred, "SL") == pytest.approx(0.5 / 0.75)


def test_as_of_excludes_later_pitches(tmp_path):
    pitches = [("2026-09-01", 0, 0, "R", "FF", "B"), ("2026-09-10", 0, 0, "R", "SL", "B")]
    m = model_for(synthetic(tmp_path, pitches), chain=["count"], half_life_days=0.0,
                  strength_overall=0.0, strength_count=0.0)
    pred = m.predict({"pitcher": "Test Pitcher", "stand": "R", "as_of": "2026-09-05"})
    assert prob(pred, "FF") == pytest.approx(1.0)
    assert pred.extras["history_pitches"] == 1


def test_previous_pitch_context_moves_toward_what_followed(tmp_path):
    # after a FF ball this pitcher always threw SL; after SL ball always FF
    pitches = []
    for _ in range(20):
        pitches += [("2026-09-01", 0, 0, "R", "FF", "B"), ("2026-09-01", 1, 0, "R", "SL", "B")]
    directory = synthetic(tmp_path, pitches)
    # make pairs share an at-bat so the second pitch sees the first as "previous"
    rows = list(csv.reader(gzip.open(directory / "data/pitchers/1.csv.gz", "rt")))
    for i in range(1, len(rows)):
        rows[i][2] = str((i - 1) // 2)
    with gzip.open(directory / "data/pitchers/1.csv.gz", "wt", newline="") as fh:
        csv.writer(fh).writerows(rows)
    load_history.cache_clear()
    base = model_for(directory, chain=["stand"], half_life_days=0.0)
    seq_model = model_for(directory, chain=["stand", "prev_type"], half_life_days=0.0, strength_prev_type=1.0)
    inputs = {"pitcher": "Test Pitcher", "stand": "R", "sequence": "FF:B"}
    assert prob(seq_model.predict(inputs), "SL") > prob(base.predict(inputs), "SL") + 0.3


def test_bad_inputs(tmp_path):
    m = model_for(synthetic(tmp_path, PITCHES))
    with pytest.raises(ValueError, match="no pitcher"):
        m.predict({"pitcher": "Nobody Atall"})
    with pytest.raises(ValueError, match="implies"):
        m.predict({"pitcher": "Test Pitcher", "sequence": "FF:B", "balls": 0, "strikes": 0})
    with pytest.raises(ValueError, match="count"):
        m.predict({"pitcher": "Test Pitcher", "balls": 4})
    with pytest.raises(ValueError, match="unknown pitch result"):
        m.predict({"pitcher": "Test Pitcher", "sequence": "FF:Q"})
    with pytest.raises(ValueError, match="no result"):
        m.predict({"pitcher": "Test Pitcher", "sequence": "FF"})
    with pytest.raises(ValueError, match="ends the at-bat"):
        m.predict({"pitcher": "Test Pitcher", "sequence": "FF:X"})
    with pytest.raises(ValueError, match="outs"):
        m.predict({"pitcher": "Test Pitcher", "outs": 3})
    with pytest.raises(ValueError, match="chain"):
        model_for(tmp_path, chain=["count", "batter"]).predict({"pitcher": "Test Pitcher"})


def test_zero_strength_on_empty_context_keeps_parent(tmp_path):
    # the pitcher never threw a 3-2 pitch: with strength 0 the count level carries no information
    d = synthetic(tmp_path, PITCHES)
    full = model_for(d, chain=["count"], half_life_days=0.0, strength_count=0.0)
    overall = model_for(d, chain=[], half_life_days=0.0)
    inputs = {"pitcher": "Test Pitcher", "stand": "R", "balls": 3, "strikes": 2}
    assert full.predict(inputs).extras["probs"] == pytest.approx(overall.predict(inputs).extras["probs"])


def test_temperature_flattens(tmp_path):
    d = synthetic(tmp_path, PITCHES)
    sharp = model_for(d).predict({"pitcher": "Test Pitcher", "stand": "R"})
    flat = model_for(d, temperature=2.0).predict({"pitcher": "Test Pitcher", "stand": "R"})
    assert prob(flat, "FF") < prob(sharp, "FF")


# ── real data (skipped until `ballmonitor fetch next_pitch` has run) ──────────

DATA = registry.model_dir("next_pitch") / "data"
needs_data = pytest.mark.skipif(not (DATA / "pitchers.csv").exists(), reason="run `ballmonitor fetch next_pitch`")


@needs_data
def test_default_example_tree_and_gbm_are_distributions():
    inputs = registry.load_example("next_pitch", "default")
    for method in ("tree", "gbm"):
        pred = registry.load_model("next_pitch", None, {"method": method}).predict(inputs)
        assert sum(pred.extras["probs"].values()) == pytest.approx(1.0, abs=1e-5)
        assert sum(o.probability for o in pred.outcomes) == pytest.approx(1.0, abs=1e-5)


@needs_data
def test_control_variant_ignores_batter_side():
    inputs = registry.load_example("next_pitch", "first_pitch")
    m = registry.load_model("next_pitch", "control")
    assert m.predict({**inputs, "stand": "L"}).extras["probs"] == m.predict({**inputs, "stand": "R"}).extras["probs"]


@needs_data
def test_site_page_is_valid():
    from ballmonitor.core import views
    from ballmonitor.models.next_pitch import site

    model = registry.load_model("next_pitch", None, {"site_pitchers": 5, "site_mix_min_pitches": 2500})
    page = site.page(model)
    assert views.check(page) == []
    picker = page["views"][0]
    assert len(picker["options"]) == 5
    for row in picker["options"][0]["views"][1]["rows"]:
        assert 0.5 < sum(v for k, v in row.items() if k != "count") <= 1.0 + 1e-6
