"""Triple Play (daily Venn puzzle): built puzzle files and the generator's invariants."""

import datetime as dt
import json
from collections import Counter
from pathlib import Path

import pytest

from ballmonitor.games.triple_play import facts, generate
from ballmonitor.games.triple_play.categories import CATEGORIES

WEB = Path(__file__).resolve().parent.parent / "ballmonitor" / "games" / "triple_play" / "web"
PUZZLES = WEB / "puzzles" / "daily"


def built():
    if not (PUZZLES / "index.json").exists():
        pytest.skip("puzzles not built")
    out = []
    for f in sorted(PUZZLES.glob("20*.json")):
        out += json.loads(f.read_text())
    return out


def test_index_matches_files():
    index = json.loads((PUZZLES / "index.json").read_text()) if (PUZZLES / "index.json").exists() else pytest.skip()
    puzzles = built()
    assert [p["date"] for p in index["puzzles"]] == [p["date"] for p in puzzles]
    assert [p["number"] for p in puzzles] == list(range(1, len(puzzles) + 1))


def test_every_puzzle_has_the_right_shape():
    for p in built():
        assert len(p["categories"]) == 3 and len({c["id"] for c in p["categories"]}) == 3
        need = generate.NEED_BIG if p["level"] == "big" else generate.NEED
        assert p["need"] == need
        assert len(p["cards"]) == sum(need.values()) == (25 if p["level"] == "big" else 17)
        assert Counter(c["region"] for c in p["cards"]) == Counter({k: v for k, v in need.items()})
        names = [c["name"] for c in p["cards"]]
        assert len(set(names)) == len(names), p["date"]
        assert all(len(c["facts"]) == 3 for c in p["cards"])


def test_no_triple_repeats_within_window():
    seen = {}
    for p in built():
        key = frozenset(c["id"] for c in p["categories"])
        day = dt.date.fromisoformat(p["date"])
        if key in seen:
            assert (day - seen[key]).days > generate.REPEAT_DAYS
        seen[key] = day


@pytest.fixture(scope="module")
def players():
    if not (facts.RAW / "People.csv").exists():
        pytest.skip("Lahman CSVs not present (data/raw is not shipped)")
    return facts.load()


def test_regions_agree_with_category_rules(players):
    for p in [q for q in built() if q["pack"] == "baseball"][:80]:
        cats = [CATEGORIES[c["id"]] for c in p["categories"]]
        for card in p["cards"]:
            pl = players[card["id"]]
            assert generate.region_of(pl, cats) == card["region"], (p["date"], card["name"])
            assert all(c.clear(pl) for c in cats), (p["date"], card["name"])


def test_generation_is_deterministic(players):
    a = generate.generate(players, dt.date(2027, 3, 1), dt.date(2027, 3, 3), log=lambda *_: None)
    b = generate.generate(players, dt.date(2027, 3, 1), dt.date(2027, 3, 3), log=lambda *_: None)
    assert a == b


def test_schedule_monday_places_sunday_big():
    for p in built():
        day = dt.date.fromisoformat(p["date"])
        assert p["pack"] == ("places" if day.weekday() == 0 else "baseball"), p["date"]
        assert (p["level"] == "big") == (day.weekday() == 6), p["date"]


def test_harder_days_have_closer_calls(players):
    import statistics
    by = {}
    for p in [q for q in built() if q["pack"] == "baseball" and q["level"] != "big"][:150]:
        cats = [CATEGORIES[c["id"]] for c in p["categories"]]
        by.setdefault(p["level"], []).append(statistics.mean(generate.closeness(players[c["id"]], cats) for c in p["cards"]))
    assert statistics.mean(by["easy"]) < statistics.mean(by["medium"]) < statistics.mean(by["hard"])


def test_places_regions_agree_with_rules():
    from ballmonitor.games.triple_play.places import model as places
    entities = places.load()
    if not entities:
        pytest.skip("places data not built")
    for p in [q for q in built() if q["pack"] == "places"]:
        cats = [places.CATEGORIES[c["id"]] for c in p["categories"]]
        for card in p["cards"]:
            e = entities[card["id"]]
            assert generate.region_of(e, cats) == card["region"], (p["date"], card["name"])
            assert all(c.clear(e) for c in cats), (p["date"], card["name"])


def test_places_known_facts():
    from ballmonitor.games.triple_play.places import model as places
    E = places.load()
    if not E:
        pytest.skip("places data not built")
    C = places.CATEGORIES
    assert C["all4"].test(E["boston"]) and C["no_s"].test(E["boston"])          # Red Sox
    assert C["has_nfl"].test(E["green_bay"]) and C["one_team"].test(E["green_bay"]) and C["ten_titles"].test(E["green_bay"])
    assert C["first_post1990"].test(E["las_vegas"]) and C["nfl_post1990"].test(E["las_vegas"])
    assert C["lost_team"].test(E["seattle"]) and C["bird"].test(E["seattle"])    # SuperSonics; Seahawks
    assert C["no_big4"].test(E["iowa"]) and C["conf_bigten"].test(E["iowa"])
    assert C["conf_sec"].test(E["texas"]) and C["region_name"].test(E["dallas_fort_worth"])   # Texas Rangers
    assert not C["borders_canada"].clear(E["ohio"])                               # debatable: water border
    assert C["capital"].test(E["austin"]) and not C["capital"].clear(E["texas"])  # cities only
    assert "new_name" not in C and "saint_name" not in C                          # visible on the card: too easy


def test_known_facts(players):
    jeter = players["jeterde01"]
    assert CATEGORIES["team_nyy"].test(jeter) and CATEGORIES["pos_ss"].test(jeter)
    assert CATEGORIES["h3000"].test(jeter) and not CATEGORIES["hr400"].test(jeter)
    assert CATEGORIES["ws"].test(jeter) and CATEGORIES["as10"].test(jeter)
    ruth = players["ruthba01"]
    assert CATEGORIES["s_hr50"].test(ruth) and CATEGORIES["hr500"].test(ruth) and CATEGORIES["hof"].test(ruth)
    bonds = players["bondsba01"]
    assert not CATEGORIES["hof"].test(bonds) and CATEGORIES["hof"].near(bonds) > 0   # on the ballot, not in
    assert CATEGORIES["s_hr50"].test(bonds) and CATEGORIES["s_3030"].test(bonds)
    # a cup of coffee is "not clear": Mays had 135 games as a Met (clear), not borderline
    assert CATEGORIES["team_nym"].clear(players["mayswi01"])


def test_web_files_present():
    for name in ("index.html", "game.js", "style.css"):
        assert (WEB / name).is_file()
