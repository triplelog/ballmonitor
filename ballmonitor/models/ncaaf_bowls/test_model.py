"""Model-level tests for ncaaf_bowls (the ballmonitor predict() contract)."""

import random

import pytest

from ballmonitor.core import registry
from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.domain import Game, Team
from ballmonitor.models.ncaaf_bowls.simulator import SeasonSimulator


def _model(**overrides):
    return registry.load_model("ncaaf_bowls", overrides={"simulations": 60, **overrides})


def test_win_probability_formula_hand_check():
    p = _model().params
    # +7 at home with HFA 2.5 and SD 14: Phi(9.5 / 14) = Phi(0.6786) = 0.7513
    assert p.formula("win_probability", rating_diff=7.0, home=1) == pytest.approx(0.7513, abs=1e-3)
    assert p.formula("win_probability", rating_diff=0.0, home=0) == pytest.approx(0.5)


def test_probabilities_valid_and_ordered():
    pred = _model().predict({"team": "Ohio State"})
    for o in pred.outcomes:
        if o.probability is not None:
            assert 0.0 <= o.probability <= 1.0
    e = pred.extras
    # Winning the title requires making the CFP; a bye requires making the CFP
    # (2026 straight seeding: byes go to the top 4 ranked teams, champions or not).
    assert e["national_champ_prob"] <= e["p_cfp"]
    assert e["p_cfp_bye"] <= e["p_cfp"]


def test_unknown_team_raises():
    with pytest.raises(ValueError, match="unknown team"):
        _model().predict({"team": "Hogwarts"})


def test_team_lookup_by_id_and_case():
    assert _model().predict({"team": "ohio_state"}).extras["team"] == "Ohio State"
    assert _model().predict({"team": "BOISE STATE"}).extras["team"] == "Boise State"


def test_full_season_is_simulated():
    # Real schedule: every team plays 12 regular-season games (13 with a Hawaii trip),
    # plus a conference title game when it qualifies.
    pred = _model().predict({"team": "Auburn"})
    w, l = (float(x) for x in pred.extras["projected_record"].split("-"))
    assert 11.99 <= w + l <= 13.01


def test_schedule_data_is_complete_and_consistent():
    import json
    from ballmonitor.models.ncaaf_bowls.config import DATA_DIR
    teams = {t["id"]: t for t in json.loads((DATA_DIR / "teams.json").read_text())}
    games = json.loads((DATA_DIR / "schedule.json").read_text()) + json.loads((DATA_DIR / "results.json").read_text())
    count = {t: 0 for t in teams}
    seen = set()
    for g in games:
        assert g["espn_id"] not in seen, "duplicate game"
        seen.add(g["espn_id"])
        for side in ("home", "away"):
            assert g[side] in teams or g[side].startswith("fcs_"), g
            if g[side] in teams:
                count[g[side]] += 1
    assert all(12 <= n <= 13 for n in count.values()), {t: n for t, n in count.items() if not 12 <= n <= 13}
    # Records in teams.json are exactly the completed results
    for t in teams.values():
        played = [g for g in json.loads((DATA_DIR / "results.json").read_text()) if t["id"] in (g["home"], g["away"])]
        assert t["wins"] + t["losses"] == len(played)


def test_formula_override_moves_result():
    # A flatter win-probability curve (bigger SD) should hurt a heavy favourite.
    base = _model().predict({"team": "Oregon"}).extras["projected_record"]
    flat = _model(margin_sd=25.0).predict({"team": "Oregon"}).extras["projected_record"]
    assert float(flat.split("-")[0]) < float(base.split("-")[0])


def test_simulation_is_reproducible():
    a = _model().predict({"team": "Georgia"}).extras
    b = _model().predict({"team": "Georgia"}).extras
    assert a == b


def test_fcs_games_count_and_respect_scenarios():
    teams = [Team("a", "A", "SEC", 10.0, 990, 8, "X", "ST", 30.0, -85.0, 4, 4, 2, 2)]
    sched = [Game(home="a", away="fcs_x", conf=False)] * 3
    sim = SeasonSimulator(teams, sched, SimConfig())
    s = sim.simulate_season(random.Random(1))["a"]
    assert s.wins + s.losses == 11
    from ballmonitor.models.ncaaf_bowls.scenarios import Scenario
    s = sim.simulate_season(random.Random(1), scenario=Scenario(loses_out={"a"}))["a"]
    assert (s.wins, s.losses) == (4, 7)



def test_site_page_is_valid_and_covers_every_team():
    import json

    from ballmonitor.core import registry, views
    from ballmonitor.models.ncaaf_bowls import site

    model = registry.load_model("ncaaf_bowls", overrides={"site_simulations": 200})
    p = views.clean(site.page(model))
    assert views.check(p) == []
    teams = p["views"][0]["rows"]
    assert len(teams) == len(json.loads((model.dir / "data" / "teams.json").read_text()))
    assert all(0 <= r["cfp"] <= 1 and 0 <= r["title"] <= r["cfp"] + 1e-9 for r in teams)
    assert abs(sum(r["title"] for r in teams) - 1) < 0.01  # exactly one champion per season


def test_playoff_rounds_and_win_distribution_add_up():
    from ballmonitor.core import registry

    res = registry.load_model("ncaaf_bowls").engine(200).run(num_sims=200)
    teams = res.team_summaries.values()
    # every simulated season has 8 quarterfinalists, 4 semifinalists, 2 finalists, 1 champion
    for field, n in (("p_cfp_quarterfinal", 8), ("p_cfp_semifinal", 4), ("p_cfp_final", 2), ("national_champ_prob", 1)):
        assert abs(sum(getattr(t, field) for t in teams) - n) < 1e-9, field
    for t in teams:
        assert t.p_cfp + 1e-9 >= t.p_cfp_quarterfinal >= t.p_cfp_semifinal >= t.p_cfp_final >= t.national_champ_prob - 1e-9
        assert t.p_cfp_quarterfinal + 1e-9 >= t.p_cfp_bye
        assert abs(sum(t.record_dist.values()) - 1) < 1e-9
        assert abs(sum(w * p for (w, _), p in t.record_dist.items()) - t.record_mean_wins) < 1e-9
        assert abs(sum(lo * p for (_, lo), p in t.record_dist.items()) - t.record_mean_losses) < 1e-9


def test_site_bubble_field_and_bracket_agree():
    from ballmonitor.core import registry, views
    from ballmonitor.models.ncaaf_bowls import site

    model = registry.load_model("ncaaf_bowls", overrides={"site_simulations": 200})
    p = views.clean(site.page(model))
    v = {x["id"]: x for x in p["views"]}
    field = v["field"]["rows"]
    assert [r["seed"] for r in field] == list(range(1, 13)) and len({r["team"] for r in field}) == 12
    seed_of = {r["team"]: r["seed"] for r in field}
    games = v["bracket"]["rows"]
    assert [g["round"] for g in games].count("First round") == 4 and games[-1]["round"] == "Championship"
    assert len(games) == 11 and all(0.5 <= g["p"] <= 1 for g in games)
    # first round: 5v12, 6v11, 7v10, 8v9 at the higher seed
    assert [g["matchup"].split(" vs ")[0].split()[1] for g in games[:4]] == ["5", "6", "7", "8"]
    for r in v["bubble"]["rows"]:  # one projection everywhere
        assert r["seed"] == seed_of.get(r["team"])
    cuts = model.params.site_bubble_cuts
    assert all(r["cfp"] >= cuts[-1] for r in v["bubble"]["rows"])
    assert p["headline"] and "title favorite" in p["headline"]


def test_single_game_mode_hand_check_and_backtest_rows():
    m = _model()
    # +7 on a neutral field, SD 14: Phi(0.5) = 0.6915; at home (+2.5): Phi(9.5 / 14) = 0.7513
    neutral = m.predict({"home_rating": 10.0, "away_rating": 3.0, "site": "neutral"})
    assert neutral.primary.probability == pytest.approx(0.6915, abs=1e-3)
    home = m.predict({"home_rating": 10.0, "away_rating": 3.0})
    assert home.primary.probability == pytest.approx(0.7513, abs=1e-3)
    assert sum(o.probability for o in home.outcomes) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="site"):
        m.predict({"home_rating": 1.0, "away_rating": 0.0, "site": "moon"})
    inputs, actual = m.backtest_case({"home": "A", "away": "B", "home_rating": "4.5", "away_rating": "10.6",
                                      "site": "home", "winner": "away", "kind": "regular season"})
    assert actual in {o.label for o in m.predict(inputs).outcomes}


def test_simulated_game_sd_keeps_single_game_spread():
    # margin_sd^2 = simulated_game_sd^2 + 2 * rating_uncertainty_points^2: 14^2 - 2 * 5^2 = 146
    p = _model(margin_sd=14.0, rating_uncertainty_points=5.0).params
    assert p.formula("simulated_game_sd") == pytest.approx(146 ** 0.5)
    assert _model(rating_uncertainty_points=0.0).params.formula("simulated_game_sd") == pytest.approx(
        _model().params.margin_sd)


def test_rating_uncertainty_widens_the_range_of_records():
    def spread(sigma):
        res = registry.load_model(
            "ncaaf_bowls", overrides={"rating_uncertainty_points": sigma, "resume_noise_points": 0.0}
        ).engine(400).run(num_sims=400)
        out = []
        for t in res.team_summaries.values():
            mean = sum(w * pr for (w, _), pr in t.record_dist.items())
            out.append(sum((w - mean) ** 2 * pr for (w, _), pr in t.record_dist.items()))
        return sum(out) / len(out)
    assert spread(6.0) > spread(0.0) * 1.05


def test_committee_sees_published_rating_and_noise_reorders():
    teams = [Team(f"t{i}", f"T{i}", "SEC", 10.0 + i, 990, 8, "X", "ST", 30.0, -85.0, 8, 2, 5, 2) for i in range(6)]
    exact = SimConfig(rating_uncertainty_points=6.0, resume_noise_points=0.0)
    states = SeasonSimulator(teams, [], exact).simulate_season(random.Random(3))
    non_champs = [s for s in states.values() if not s.is_conf_champ and not s.conf_runner_up]
    # same record, no noise: ranked by the published rating whatever was drawn for the games
    assert sorted(non_champs, key=lambda s: s.resume_score) == sorted(non_champs, key=lambda s: s.published_rating)
    assert any(abs(s.rating - s.published_rating) > 0.5 for s in states.values())
    noisy = SimConfig(rating_uncertainty_points=0.0, resume_noise_points=10.0)
    orders = set()
    for seed in range(8):
        st = SeasonSimulator(teams, [], noisy).simulate_season(random.Random(seed))
        orders.add(tuple(sorted(st, key=lambda k: st[k].resume_score)))
    assert len(orders) > 1


# ── who to root for this week (site.py) ─────────────────────────────────────────

def test_this_week_is_the_next_week_with_games_still_to_play():
    import datetime as dt

    from ballmonitor.models.ncaaf_bowls import site
    sched = [
        {"home": "a", "away": "b", "week": 10, "date": "2026-11-08"},    # last week, not in the results yet
        {"home": "c", "away": "d", "week": 11, "date": "2026-11-14"},
        {"home": "e", "away": "fcs_x", "week": 11, "date": "2026-11-14"},  # FCS opponent: not tracked
        {"home": "f", "away": "g", "week": 11, "date": "2026-11-15"},
        {"home": "h", "away": "i", "week": 12, "date": "2026-11-21"},
    ]
    games, when = site.this_week(sched, today=dt.date(2026, 11, 11))
    assert games == [1, 3] and when == "Nov 14-15"
    assert site.this_week(sched, today=dt.date(2026, 12, 31)) == ([], "")


def test_tracked_games_split_each_teams_chances_consistently():
    """The overall chance is the mix of the two conditional chances, and a contender's own game
    moves its playoff chance the right way."""
    import json

    from ballmonitor.models.ncaaf_bowls import site
    model = registry.load_model("ncaaf_bowls")
    schedule = json.loads((model.dir / "data" / "schedule.json").read_text())
    fbs = [i for i, g in enumerate(schedule) if not (g["home"].startswith("fcs_") or g["away"].startswith("fcs_"))]
    games = fbs[:6]
    n = 600
    res = model.engine(n).run(num_sims=n, track_games=games)
    assert set(res.game_tallies) == set(games)
    for g in games:
        tally = res.game_tallies[g]
        assert 0 < tally.home_wins < n
        for team_id, s in res.team_summaries.items():
            total = round(s.p_cfp * n)
            p_home, p_away, n_home, n_away = tally.split(tally.cfp_if_home[team_id], total, n)
            assert p_home * n_home + p_away * n_away == pytest.approx(total)
        home = res.team_summaries[tally.home]
        if 0.05 < home.p_cfp < 0.95:   # a contender is likelier to make it when it wins
            p_home, p_away, *_ = tally.split(tally.cfp_if_home[tally.home], round(home.p_cfp * n), n)
            assert p_home > p_away


def test_root_for_lists_the_teams_own_game_first_and_skips_noise():
    import json

    from ballmonitor.models.ncaaf_bowls import site
    model = registry.load_model("ncaaf_bowls")
    schedule = json.loads((model.dir / "data" / "schedule.json").read_text())
    games, _ = site.this_week(schedule, today=__import__("datetime").date.fromisoformat(
        min(g["date"] for g in schedule)))
    if not games:
        pytest.skip("no games left in the schedule")
    res = model.engine(2000).run(num_sims=2000, track_games=games)
    names = {t["id"]: t["name"] for t in json.loads((model.dir / "data" / "teams.json").read_text())}
    p = model.params
    shown = 0
    for team_id, s in res.team_summaries.items():
        what, rows = site.root_for(team_id, s, res, schedule, games, names, p)
        if not rows:
            continue
        shown += 1
        assert what in ("playoff", "conference title") and len(rows) <= int(p.site_root_rows)
        plays = [g for g in games if team_id in (schedule[g]["home"], schedule[g]["away"])]
        if plays:   # its own game first, rooting for itself
            assert rows[0]["root"] == s.team_name
        for r in rows[1 if plays else 0:]:   # someone else's game: listed only for the side that helps
            assert r["if_win"] >= r["if_lose"] and r["diff"] == pytest.approx(r["if_win"] - r["if_lose"])
    assert shown > 0
    # a team with no realistic chance at the playoff or its conference gets no table
    hopeless = next((t for t, s in res.team_summaries.items()
                     if s.p_cfp < float(p.site_root_min_chance) and s.p_conf_champ < float(p.site_root_min_chance)), None)
    if hopeless:
        assert site.root_for(hopeless, res.team_summaries[hopeless], res, schedule, games, names, p) == ("", [])
