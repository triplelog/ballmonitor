import datetime as dt
import random

import pytest

from ballmonitor.core import registry
from ballmonitor.models.college_diamond import data as D
from ballmonitor.models.college_diamond.model import fast_formula, find_team
from ballmonitor.models.college_diamond.ratings import RatingParams, fit, midweek_flags, transform
from ballmonitor.models.college_diamond.rpi import RpiState, RpiWeights, ranks, rpi
from ballmonitor.models.college_diamond.sim import SimInputs, SimParams, Simulator

FAST = {"simulations": 60}


def run(inputs, variant=None, **overrides):
    return registry.load_model("college_diamond", variant, {**FAST, **overrides}).predict(inputs)


# ── RPI on a hand-checked toy schedule ─────────────────────────────────────────
# A beats B at A; C beats B at B; A beats C on a neutral field.
TOY = [("A", "B", 1.0, False), ("B", "C", 0.0, False), ("C", "A", 0.0, True)]
UNWEIGHTED = RpiWeights(home_win=1, road_win=1, home_loss=1, road_loss=1)


def test_rpi_unweighted_by_hand():
    # WP: A 1, B 0, C .5. OWP (opponents' WP without games vs the team): every team .5.
    # OOWP: every team .5.  RPI = .25 WP + .5 OWP + .25 OOWP.
    r = rpi(TOY, UNWEIGHTED)
    assert r["A"] == pytest.approx(0.625)
    assert r["B"] == pytest.approx(0.375)
    assert r["C"] == pytest.approx(0.5)
    assert ranks(r) == {"A": 1, "C": 2, "B": 3}


def test_rpi_baseball_site_weights_by_hand():
    # C: road win 1.3, neutral loss 1.0 -> WP 1.3 / 2.3. A: 0.7 + 1 wins, no losses -> 1.
    r = rpi(TOY)
    assert r["C"] == pytest.approx(0.25 * 1.3 / 2.3 + 0.375)
    assert r["A"] == pytest.approx(0.625)
    assert r["B"] == pytest.approx(0.375)


def test_incremental_rpi_matches_full():
    games = [g for g in D.season_games("baseball", 2024) if g.game_type == "R"]
    res = [(g.home, g.away, 1.0 if g.margin > 0 else 0.0, g.neutral) for g in games]
    full = rpi(res)
    inc = RpiState(res[:5000]).compute(res[5000:])
    assert max(abs(full[t] - inc[t]) for t in full) < 1e-12


# ── ratings ──────────────────────────────────────────────────────────────────
def test_margin_transform():
    assert transform(16, 10, 0.5) == pytest.approx(10 ** 0.5)
    assert transform(-4, 10, 1.0) == -4
    assert transform(0, 10, 0.7) == 0


def test_ratings_recover_a_simple_ordering():
    G = [D.Game(2030, f"2030-03-{d:02d}", "R", h, a, hs, as_, False, 0, False, "")
         for d, (h, a, hs, as_) in enumerate([("A", "B", 5, 1), ("B", "C", 4, 2), ("A", "C", 7, 1),
                                               ("B", "A", 2, 3), ("C", "B", 1, 3), ("C", "A", 0, 6)], start=1)]
    r = fit(G, RatingParams(ridge=1.0, half_life_days=0.0), dt.date(2030, 4, 1))
    assert r.weekend["A"] > r.weekend["B"] > r.weekend["C"]


def test_midweek_flags():
    mk = lambda day, h, a: D.Game(2030, day, "R", h, a, 1, 0, False, 0, False, "")  # noqa: E731
    G = [mk("2030-03-05", "A", "B"),                       # Tuesday single game: midweek
         mk("2030-03-07", "A", "C"), mk("2030-03-08", "A", "C"), mk("2030-03-09", "A", "C")]  # Thu-Sat series
    assert midweek_flags(G) == [True, False, False, False]


def test_stdlib_and_numpy_solvers_agree():
    pytest.importorskip("numpy")
    from ballmonitor.models.college_diamond.research_strength import fit_np
    G = [g for g in D.season_games("softball", 2024) if g.date < "2024-04-15"]
    p = RatingParams(margin_cap=8, margin_power=0.7, ridge=6, half_life_days=60, split_midweek=True,
                     midweek_ridge=10, midweek_beta=0.2)
    a = fit(G, p, dt.date(2024, 4, 15))
    r, m, H = fit_np(G, midweek_flags(G), p, dt.date(2024, 4, 15))
    assert a.home_edge == pytest.approx(H, abs=1e-4)
    assert max(abs(a.weekend[t] - r[t]) for t in r) < 1e-4
    assert max(abs(a.midweek[t] - m[t]) for t in m) < 1e-4


# ── bracket mechanics ────────────────────────────────────────────────────────
def toy_sim(prob=None, teams=4):
    names = [f"T{i}" for i in range(teams)]
    si = SimInputs("baseball", 2030, dt.date(2030, 5, 1), {t: {"name": t, "conference": "X"} for t in names},
                   [], [], {t: -i for i, t in enumerate(names)}, {}, 0.0, {}, {}, {})
    sp = SimParams(1, 1, prob or (lambda d: 1.0 if d > 0 else 0.0 if d < 0 else 0.5),
                   lambda *a: 0.0, lambda *a: 0.0, 1.0, 0.5)
    return Simulator(si, sp), names


def test_double_elimination_favourite_wins_in_six_games():
    sim, names = toy_sim()
    log = []
    champ = sim.double_elim(random.Random(1), names, sim.si.rating, log)
    assert champ == "T0"
    assert len(log) == 6  # 1v4, 2v3, winners, losers, elimination, final


def test_double_elimination_champion_has_at_most_one_loss_and_others_two():
    sim, names = toy_sim(prob=lambda d: 0.5)
    for seed in range(50):
        log = []
        champ = sim.double_elim(random.Random(seed), names, sim.si.rating, log)
        losses = {t: 0 for t in names}
        for a, b, w, _ in log:
            losses[b if w == a else a] += 1
        assert losses[champ] <= 1
        assert all(losses[t] == 2 for t in names if t != champ)
        assert len(log) in (6, 7)


def test_best_of_three():
    sim, names = toy_sim(prob=lambda d: 0.5)
    for seed in range(30):
        log = []
        w = sim.series(random.Random(seed), "T0", "T1", sim.si.rating, log, 3)
        assert len(log) in (2, 3)
        assert sum(1 for *_, x, _n in log if x == w) == 2


def test_single_elimination_with_staggered_byes():
    sim, names = toy_sim(teams=16)
    log = []
    champ = sim.single_elim(random.Random(1), names, sim.si.rating, log, byes=4)
    assert champ == "T0" and len(log) == 15
    # seeds 1-4 play only three games (quarterfinal, semifinal, final)
    assert sum(1 for a, b, *_ in log if "T0" in (a, b)) == 3


def test_regional_placement_s_curve_and_conference_separation():
    sim, _ = toy_sim()
    confs = ["C%d" % (i % 10) for i in range(64)]
    teams = {f"t{i}": {"name": f"t{i}", "conference": confs[i]} for i in range(64)}
    sim.conf_of = {t: v["conference"] for t, v in teams.items()}
    order = list(teams)
    regs = sim.place(order[:16], order[16:])
    assert [r[0] for r in regs] == order[:16]
    assert sorted(t for r in regs for t in r) == sorted(order)
    for r in regs:
        assert len(r) == 4
        assert len({sim.conf_of[t] for t in r}) == 4  # no conference-mates


# ── whole model ──────────────────────────────────────────────────────────────
def test_probabilities_valid_and_monotone_across_rounds():
    pred = run({"sport": "baseball", "season": 2024, "as_of": "2024-05-01"})
    for t, s in pred.extras["teams"].items():
        for k in ("bid", "auto_bid", "host", "national_seed", "regional", "super", "finals", "title"):
            assert 0.0 <= s[k] <= 1.0
        assert s["bid"] >= s["regional"] >= s["super"] >= s["finals"] >= s["title"]
        assert s["bid"] >= s["host"] >= s["national_seed"] - 1e-12
        assert s["auto_bid"] <= s["bid"]
    n = pred.extras["simulations"]
    assert sum(s["bid"] for s in pred.extras["teams"].values()) == pytest.approx(64, abs=1e-9 * n)
    assert sum(s["title"] for s in pred.extras["teams"].values()) == pytest.approx(1.0)
    assert sum(s["host"] for s in pred.extras["teams"].values()) == pytest.approx(16)


def test_reproducible_with_seed_and_changes_with_seed():
    inp = {"sport": "softball", "season": 2025, "as_of": "2025-04-15", "team": "Oklahoma"}
    a, b = run(inp, seed=7), run(inp, seed=7)
    c = run(inp, seed=8)
    assert a.extras["teams"] == b.extras["teams"]
    assert a.extras["teams"] != c.extras["teams"]


def test_primary_outcome_is_p_bid():
    pred = run({"sport": "baseball", "season": 2026, "as_of": "2026-05-01", "team": "UCLA"})
    assert "makes the NCAA field" in pred.primary.label
    assert pred.primary.probability == pred.extras["teams"]["ucla"]["bid"]


def test_completed_games_are_respected_at_selection_eve():
    pred = run({"sport": "baseball", "season": 2025, "as_of": "selection"})
    # every regular-season game is done: regular-season records have no spread
    s = pred.extras["teams"]["lsu"]
    assert s["reg_wins_iv"][0] == s["reg_wins_iv"][1]
    # finished conference tournaments keep their real champion in every simulation
    assert pred.extras["finished_tournaments"]
    for conf, champ in pred.extras["finished_tournaments"].items():
        assert pred.extras["teams"][champ]["conf_tourney"] == pytest.approx(1.0)


def test_steeper_win_curve_helps_the_favourite():
    inp = {"sport": "baseball", "season": 2026, "as_of": "selection"}
    flat = run(inp, baseball_win_scale=0.3, simulations=200)
    steep = run(inp, baseball_win_scale=2.0, simulations=200)
    top = max(flat.extras["rating"], key=flat.extras["rating"].get)
    assert steep.extras["teams"][top]["title"] > flat.extras["teams"][top]["title"]


def test_no_committee_noise_makes_selection_eve_bids_nearly_certain():
    inp = {"sport": "baseball", "season": 2024, "as_of": "selection"}
    pred = run(inp, committee_noise=0.0, rating_uncertainty=0.0, simulations=30)
    bids = [s["bid"] for s in pred.extras["teams"].values()]
    assert all(b in (0.0, 1.0) for b in bids)


def test_fast_formula_matches_engine():
    m = registry.load_model("college_diamond")
    f = fast_formula(m.params, "selection_score")
    v = dict(rpi_rank=17, rating_rank=40, win_pct=0.6, sel_rpi=6.0)
    assert f(**v) == pytest.approx(m.params.formula("selection_score", **v))


def test_find_team_by_name_or_id():
    teams = D.load_teams("baseball")[2026]
    assert find_team("Georgia Tech", teams) == "georgia-tech"
    assert find_team("mississippi-st", teams) == "mississippi-st"
    with pytest.raises(ValueError):
        find_team("Not A Team", teams)


def test_bad_inputs():
    with pytest.raises(ValueError):
        run({"sport": "cricket", "season": 2024})
    with pytest.raises(ValueError):
        run({"sport": "baseball", "season": 2020})


def test_site_views_build():
    """The public page's per-sport views (fewer simulations and one trend date: the full
    page takes ~30 s)."""
    from ballmonitor.core import views
    from ballmonitor.models.college_diamond import site

    model = registry.load_model("college_diamond", None, {**FAST, "site_trend_dates": ["04-01"]})
    vs, _ = site._sport_views(model, model, "softball")
    p = views.page(title="t", summary="s", sport="College baseball & softball", views=vs)
    assert views.check(p) == []
    tourney, power, trend = vs
    assert len(tourney["rows"]) == 64
    assert [r["rank"] for r in power["rows"][:3]] == [1, 2, 3]
    assert abs(sum(r["rating"] for r in power["rows"]) / len(power["rows"])) < 1e-6  # centred
    assert all(len(s["points"]) == 2 for s in trend["series"])
