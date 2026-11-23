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


def new_rules(p) -> bool:
    """Baseball puzzles built with the team + position + stat rules (earlier ones kept as published)."""
    return p["pack"] == "baseball" and dt.date.fromisoformat(p["date"]) >= generate.RULES_SINCE


def test_every_puzzle_has_the_right_shape():
    for p in built():
        assert len(p["categories"]) == 3 and len({c["id"] for c in p["categories"]}) == 3
        if p["pack"] == "players":   # Monday's three players: one card per part, no spares
            need, spare = generate.NEED_PLAYERS, 0
            assert sum(need.values()) == 8
        elif new_rules(p):   # baseball: 11 spots (Sunday 14), no spare cards
            need = generate.NEED_BASEBALL_BIG if p["level"] == "big" else generate.NEED_BASEBALL
            spare = generate.SPARE_BASEBALL
            assert sum(need.values()) == (14 if p["level"] == "big" else 11)
        else:              # cities & states, and baseball before RULES_SINCE: 17 (Sunday 25) + a spare per part
            need = generate.NEED_BIG if p["level"] == "big" else generate.NEED
            spare = generate.SPARE
            assert sum(need.values()) == (25 if p["level"] == "big" else 17)
        assert p["need"] == need, p["date"]
        assert Counter(c["region"] for c in p["cards"]) == Counter({k: v + spare for k, v in need.items()}), p["date"]
        assert len(p["cards"]) == sum(need.values()) + spare * len(need)
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
    for p in [q for q in built() if new_rules(q)][:120]:
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
        monday = "players" if day >= generate.PLAYERS_SINCE else "places"
        assert p["pack"] == (monday if day.weekday() == 0 else "baseball"), p["date"]
        assert (p["level"] == "big") == (day.weekday() == 6), p["date"]


def test_harder_days_have_closer_calls(players):
    import statistics
    by = {}
    # Every level avoids close calls (clear-cut players only), so the averages are all near 0 and
    # easy vs medium is noise; what holds is that hard days allow the most (over every day built).
    for p in [q for q in built() if new_rules(q) and q["level"] != "big"]:
        cats = [CATEGORIES[c["id"]] for c in p["categories"]]
        by.setdefault(p["level"], []).append(statistics.mean(generate.closeness(players[c["id"]], cats) for c in p["cards"]))
    assert statistics.mean(by["hard"]) > max(statistics.mean(by["easy"]), statistics.mean(by["medium"]))


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
    # a fan ties Mays to the Giants, not to his two late seasons as a Met: never used with the Mets
    mays = players["mayswi01"]
    assert CATEGORIES["team_sfg"].clear(mays) and not CATEGORIES["team_nym"].clear(mays)
    assert CATEGORIES["pos_of"].test(mays) and CATEGORIES["pos_of"].clear(mays)
    # positions: 75% of games; split careers are left out
    assert CATEGORIES["pos_ss"].test(jeter) and not CATEGORIES["pos_ss"].test(players["rodrial01"])
    assert not CATEGORIES["pos_ss"].clear(players["rodrial01"])          # A-Rod: SS then 3B
    assert CATEGORIES["pos_p"].test(players["maddugr01"]) and CATEGORIES["pos_p"].clear(players["maddugr01"])
    assert not CATEGORIES["pos_p"].clear(players["ruthba01"])            # 163 games pitched: arguable
    assert not CATEGORIES["pos_p"].clear(players["ohtansh01"])
    assert CATEGORIES["pos_c"].test(players["benchjo01"]) and CATEGORIES["pos_c"].clear(players["benchjo01"])
    # stats: nobody near the line (Jeter's 260 HR is far from 400; 380 would be left out)
    assert CATEGORIES["hr400"].clear(jeter) and not CATEGORIES["hr400"].clear({**jeter, "bat": {**jeter["bat"], "HR": 380}})


def test_team_position_and_stat_every_baseball_day(players):
    for p in [q for q in built() if new_rules(q)]:
        cats = [CATEGORIES[c["id"]] for c in p["categories"]]
        kinds = sorted("team" if c.kind == "team" else "position" if c.kind == "position" else "stat" for c in cats)
        assert kinds == ["position", "stat", "team"], p["date"]
        pos = next(c for c in cats if c.kind == "position")
        stat = next(c for c in cats if c.kind not in ("team", "position"))
        if pos.id == "pos_p":
            assert stat.hitters is None, (p["date"], stat.id)     # works for batters too
        else:
            assert stat.hitters is not False, (p["date"], stat.id)


def test_web_files_present():
    for name in ("index.html", "game.js", "style.css"):
        assert (WEB / name).is_file()


def test_three_players_cards_are_true_and_clear_cut(players):
    """Monday's three players: every card sits where it's true of exactly those players, is
    clear-cut for all three, and each puzzle has a team, a position and another card."""
    days = [p for p in built() if p["pack"] == "players"]
    assert days
    seen = {}
    for p in days:
        trio = [players[c["id"]] for c in p["categories"]]
        kinds = set()
        for card in p["cards"]:
            cat = CATEGORIES[card["id"]]
            assert all(cat.clear(x) for x in trio), (p["date"], card["name"])
            assert "".join(l for l, x in zip("ABC", trio) if cat.test(x)) == card["region"], (p["date"], card["name"])
            kinds.add(cat.kind if cat.kind in ("team", "position") else "other")
        assert kinds == {"team", "position", "other"}, p["date"]
        day = dt.date.fromisoformat(p["date"])
        for c in p["categories"]:   # no player twice within the repeat window
            assert c["id"] not in seen or (day - seen[c["id"]]).days > generate.REPEAT_DAYS * 3, (p["date"], c["label"])
            seen[c["id"]] = day
