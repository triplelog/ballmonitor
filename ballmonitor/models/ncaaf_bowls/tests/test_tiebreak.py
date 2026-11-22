"""Conference title-game tiebreakers (tiebreak.py), on hand-built standings."""

import random
from collections import Counter

from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.domain import Team
from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator
from ballmonitor.models.ncaaf_bowls.tiebreak import rank_standings


def _beat(*games: str) -> Counter:
    """'a>b' = a beat b in a conference game."""
    return Counter(tuple(g.split(">")) for g in games)


def test_no_tie_goes_by_conference_win_pct():
    pct = {"a": 0.5, "b": 1.0, "c": 0.75}
    assert rank_standings(["a", "b", "c"], pct, {}, {"a": 30, "b": 0, "c": 10}) == ["b", "c", "a"]


def test_two_way_tie_head_to_head_beats_rating():
    pct = {"a": 0.75, "b": 0.75, "c": 0.5}
    assert rank_standings(["a", "b", "c"], pct, _beat("b>a"), {"a": 20, "b": 0, "c": 0})[:2] == ["b", "a"]


def test_two_way_tie_without_meeting_uses_common_opponents_then_rating():
    pct = {"a": 0.75, "b": 0.75, "x": 0.5, "y": 0.5}
    # both played x and y: a 2-0, b 1-1 against them
    beat = _beat("a>x", "a>y", "x>b", "b>y")
    assert rank_standings(["a", "b", "x", "y"], pct, beat, {"a": 0, "b": 20}, places=2) == ["a", "b"]
    # same record against the common opponents: the rating decides
    beat = _beat("a>x", "y>a", "x>b", "b>y")
    assert rank_standings(["a", "b", "x", "y"], pct, beat, {"a": 0, "b": 20}, places=2) == ["b", "a"]


def test_three_way_round_robin_combined_head_to_head():
    # a beat b and c (2-0); b beat c (1-1); c 0-2. The best-rated team (c) gets nothing.
    pct = {"a": 0.75, "b": 0.75, "c": 0.75}
    beat = _beat("a>b", "a>c", "b>c")
    assert rank_standings(["c", "b", "a"], pct, beat, {"a": 0, "b": 1, "c": 30}) == ["a", "b", "c"]


def test_three_way_circle_falls_to_common_opponents_then_two_team_rule():
    # a>b>c>a: every team 1-1 in the mini round robin. Common opponent x: a and c beat it, b lost.
    pct = {"a": 0.75, "b": 0.75, "c": 0.75, "x": 0.0}
    beat = _beat("a>b", "b>c", "c>a", "a>x", "c>x", "x>b")
    # a and c lead; the two-team rule restarts: c beat a head-to-head, so c is first
    # (rating would have said a); then a and b: a beat b
    order = rank_standings(["a", "b", "c", "x"], pct, beat, {"a": 25, "b": 20, "c": 0})
    assert order[:3] == ["c", "a", "b"]


def test_three_way_circle_with_nothing_else_goes_to_rating():
    pct = {"a": 0.75, "b": 0.75, "c": 0.75}
    beat = _beat("a>b", "b>c", "c>a")
    # b has the best rating; once b is set, a and c revert to the two-team rule: c beat a,
    # despite a's better rating
    assert rank_standings(["a", "b", "c"], pct, beat, {"a": 6, "b": 9, "c": 5}) == ["b", "c", "a"]


def test_three_way_without_round_robin_sweep_and_swept():
    pct = {"a": 0.75, "b": 0.75, "c": 0.75}
    # a beat b and c; b and c never met: a first, then b and c by rating
    assert rank_standings(["a", "b", "c"], pct, _beat("a>b", "a>c"), {"a": 0, "b": 1, "c": 2}) == ["a", "c", "b"]
    # c lost to a and b, a and b never met: c drops out, a vs b goes to the rating
    assert rank_standings(["a", "b", "c"], pct, _beat("a>c", "b>c"), {"a": 0, "b": 1, "c": 99}, places=2) == ["b", "a"]


def test_four_way_tie_round_robin():
    # combined head-to-head among a, b, c, d: a 3-0, b 2-1, c 1-2, d 0-3
    pct = {t: 0.625 for t in "abcd"}
    beat = _beat("a>b", "a>c", "a>d", "b>c", "b>d", "c>d")
    assert rank_standings(list("dcba"), pct, beat, {"a": 0, "b": 0, "c": 50, "d": 99}) == list("abcd")


def test_four_way_tie_two_lead_then_head_to_head_between_them():
    # round robin: a and b 2-1, c and d 1-2; b beat a. Common opponent x would favour a.
    pct = {"a": 0.6, "b": 0.6, "c": 0.6, "d": 0.6, "x": 0.0}
    beat = _beat("b>a", "a>c", "a>d", "c>b", "b>d", "d>c", "a>x", "x>b", "c>x", "d>x")
    order = rank_standings(["a", "b", "c", "d", "x"], pct, beat, {"a": 10, "b": 0, "c": 30, "d": 20})
    # b first (beat a); then a, c, d start again: a 2-0 among them -> a; then c vs d: d beat c
    assert order[:4] == ["b", "a", "d", "c"]


def test_four_way_tie_without_round_robin_uses_common_opponents():
    # a, b, c, d level; only a-b and c-d met (no sweep, nobody swept). Common opponents x and y:
    # c 2-0, a 1-1, b 1-1, d 0-2 -> c first; then a, b, d: no sweep (a beat b, but a-d never met)...
    pct = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5, "x": 0.4, "y": 0.4}
    beat = _beat("a>b", "d>c", "c>x", "c>y", "a>x", "y>a", "b>x", "y>b", "x>d", "y>d")
    order = rank_standings(["a", "b", "c", "d", "x", "y"], pct, beat, {"a": 0, "b": 0, "c": 0, "d": 50}, places=2)
    # ... common opponents: a 1-1, b 1-1, d 0-2 -> a and b; two-team rule: a beat b
    assert order == ["c", "a"]


def test_coin_flip_only_when_level_on_everything():
    pct = {"a": 1.0, "b": 1.0}
    firsts = {rank_standings(["a", "b"], pct, {}, {"a": 3, "b": 3}, rng=random.Random(s))[0] for s in range(20)}
    assert firsts == {"a", "b"}


def _team(tid, conf_w, conf_l, rating):
    return Team(tid, tid.upper(), "SEC", rating, 990, 8, "X", "ST", 30.0, -85.0, 8, 4, conf_w, conf_l)


def test_simulator_uses_played_conference_games_for_the_title_game():
    """Three teams 6-2 in conference, a round robin already played (results.json rows): a 2-0,
    b 1-1, c 0-2. The title game is a vs b every season, though c is rated far higher."""
    teams = [_team("a", 6, 2, 0.0), _team("b", 6, 2, 1.0), _team("c", 6, 2, 30.0), _team("d", 2, 6, 0.0)]
    results = [{"home": "a", "away": "b", "conf": True, "home_score": 21, "away_score": 14},
               {"home": "c", "away": "a", "conf": True, "home_score": 10, "away_score": 17},
               {"home": "b", "away": "c", "conf": True, "home_score": 28, "away_score": 27},
               {"home": "c", "away": "b", "conf": False, "home_score": 50, "away_score": 0}]  # not conference
    sim = SeasonSimulator(teams, [], SimConfig(rating_uncertainty_points=0.0), results=results)
    for seed in range(5):
        st = sim.simulate_season(random.Random(seed))
        assert {t for t, s in st.items() if s.is_conf_champ or s.conf_runner_up} == {"a", "b"}
    # without the results it falls back to the rating: c always plays
    plain = SeasonSimulator(teams, [], SimConfig(rating_uncertainty_points=0.0))
    st = plain.simulate_season(random.Random(0))
    assert st["c"].is_conf_champ or st["c"].conf_runner_up


def _div_team(tid, conf_w, conf_l, rating, division):
    t = _team(tid, conf_w, conf_l, rating)
    t.conf, t.division = "Sun Belt", division
    return t


def test_division_winners_meet_in_the_title_game():
    """East: e1 7-1, e2 7-1 (e2 beat e1), e3 6-2 but rated far higher. West: w1 5-3, w2 4-4.
    The conference's best two records are both East; the title game is still East vs West:
    e2 (head-to-head) against w1."""
    teams = [_div_team("e1", 7, 1, 10.0, "East"), _div_team("e2", 7, 1, 0.0, "East"),
             _div_team("e3", 6, 2, 30.0, "East"), _div_team("w1", 5, 3, 0.0, "West"),
             _div_team("w2", 4, 4, 20.0, "West")]
    results = [{"home": "e2", "away": "e1", "conf": True, "home_score": 24, "away_score": 21}]
    sim = SeasonSimulator(teams, [], SimConfig(rating_uncertainty_points=0.0), results=results)
    for seed in range(5):
        st = sim.simulate_season(random.Random(seed))
        assert {t for t, s in st.items() if s.is_conf_champ or s.conf_runner_up} == {"e2", "w1"}


def test_division_tiebreak_counts_cross_division_common_opponents():
    # e1 and e2 level and never met; both played w1 (East-West): e1 won, e2 lost -> e1
    pct = {"e1": 0.75, "e2": 0.75, "w1": 0.5}
    beat = _beat("e1>w1", "w1>e2")
    assert rank_standings(["e1", "e2"], pct, beat, {"e1": 0, "e2": 9}, places=1,
                          opponents=["e1", "e2", "w1"]) == ["e1"]
    # without the conference-wide pool there is no common opponent and the rating decides
    assert rank_standings(["e1", "e2"], pct, beat, {"e1": 0, "e2": 9}, places=1) == ["e2"]


def test_sun_belt_has_east_and_west_and_never_pairs_one_division():
    import json

    from ballmonitor.core import registry
    from ballmonitor.models.ncaaf_bowls.config import DATA_DIR
    teams = json.loads((DATA_DIR / "teams.json").read_text())
    sb = {t["id"]: t["division"] for t in teams if t["conf"] == "Sun Belt"}
    assert set(sb.values()) == {"East", "West"} and len(sb) == 14
    eng = registry.load_model("ncaaf_bowls").engine(300)
    rng = random.Random(11)
    for _ in range(300):
        st = eng.simulator.simulate_season(rng)
        pair = [s for s in st.values() if s.conf == "Sun Belt" and (s.is_conf_champ or s.conf_runner_up)]
        assert sorted(sb[s.id] for s in pair) == ["East", "West"]
