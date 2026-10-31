import itertools
import random
from pathlib import Path

import pytest

from ballmonitor.core import registry
from ballmonitor.models.ranked_choice import ballots as data
from ballmonitor.models.ranked_choice import voting as v

DATA = Path(__file__).parent / "data" / "ballots"
M, N, C, K = "Memphis", "Nashville", "Chattanooga", "Knoxville"
TENNESSEE = [[M, N, C, K]] * 42 + [[N, C, K, M]] * 26 + [[C, K, N, M]] * 15 + [[K, C, N, M]] * 17
CANDS = [M, N, C, K]


def run(inputs, variant=None, **overrides):
    return registry.load_model("ranked_choice", variant, overrides).predict(inputs)


# ---- textbook example (Wikipedia "Tennessee capital") ------------------------------------

def test_tennessee_winners():
    d = v.pairwise(TENNESSEE, CANDS)
    assert v.condorcet_winner(d, CANDS) == N and v.condorcet_loser(d, CANDS) == M
    assert v.plurality(TENNESSEE, CANDS, {}).order[0] == M
    assert v.elimination("irv", TENNESSEE, CANDS, {}).order[0] == K
    for kind in ("coombs", "baldwin", "bucklin"):
        assert v.elimination(kind, TENNESSEE, CANDS, {}).order[0] == N
    for f in (v.copeland, v.schulze, v.ranked_pairs, v.minimax, v.kemeny):
        assert f(d, CANDS, {}).order[0] == N


def test_tennessee_borda_scores():
    # Borda 3-2-1-0 over 4 places: Nashville 194, Chattanooga 173, Memphis 126, Knoxville 107
    r = v.positional(TENNESSEE, CANDS, lambda rank, n: n - rank, {})
    assert r.order == [N, C, M, K]
    assert [r.scores[c] for c in r.order] == [194, 173, 126, 107]


def test_tennessee_full_model():
    pred = run(registry.load_example("ranked_choice", "tennessee"))
    assert pred.primary.label == "Winner (Schulze): Nashville"
    winners = {o.label: o.note for o in pred.outcomes if o.group.startswith("Winner by method")}
    assert winners["Plurality"].startswith("Memphis") and winners["Instant runoff"].startswith("Knoxville")
    assert pred.extras["condorcet_winner"] == N
    grid = pred.tables[0]
    assert grid.columns[0] == "Candidate" and len(grid.rows) == 4


def test_method_param_switches_primary():
    pred = run(registry.load_example("ranked_choice", "tennessee"), method="irv")
    assert pred.primary.label == "Winner (Instant runoff): Knoxville"
    assert "official winner: Nashville" in pred.primary.note  # no points table -> official = Borda


# ---- engine properties ------------------------------------------------------------------

def test_pairwise_truncation_rules():
    ballots = [["a", "b"], ["c"]]
    below = v.pairwise(ballots, ["a", "b", "c"], "below")
    assert below["a"]["c"] == 1 and below["c"]["a"] == 1 and below["b"]["c"] == 1
    ignore = v.pairwise(ballots, ["a", "b", "c"], "ignore")
    assert ignore["a"]["c"] == 0 and ignore["c"]["a"] == 0 and ignore["a"]["b"] == 1


def test_cycle_has_no_condorcet_winner_and_smith_set_is_the_cycle():
    ballots = [["a", "b", "c"]] * 4 + [["b", "c", "a"]] * 3 + [["c", "a", "b"]] * 2 + [["d"]]
    cands = ["a", "b", "c", "d"]
    d = v.pairwise(ballots, cands)
    assert v.condorcet_winner(d, cands) is None
    assert set(v.smith_set(d, cands, {})) == {"a", "b", "c"}
    # ranked pairs locks a>b (7) and b>c (7) before c>a (5): a wins
    assert v.ranked_pairs(d, cands, {}).order[:3] == ["a", "b", "c"]


def test_kemeny_exact_matches_brute_force():
    rng = random.Random(3)
    for _ in range(20):
        cands = list("ABCDEF")
        ballots = [rng.sample(cands, rng.randint(1, 6)) for _ in range(11)]
        d = v.pairwise(ballots, cands)
        best = max(v.kemeny_score(d, list(p)) for p in itertools.permutations(cands))
        assert v.kemeny_score(d, v.kemeny(d, cands, {}).order) == best


def test_every_method_returns_a_full_order():
    rng = random.Random(7)
    cands = [f"t{i}" for i in range(30)]
    ballots = [sorted(cands, key=lambda c: int(c[1:]) + rng.gauss(0, 6))[:10] for _ in range(25)]
    d = v.pairwise(ballots, cands)
    results = [v.positional(ballots, cands, lambda r, n: 11 - r, {}), v.plurality(ballots, cands, {}),
               v.copeland(d, cands, {}), v.schulze(d, cands, {}), v.ranked_pairs(d, cands, {}),
               v.minimax(d, cands, {}), v.kemeny(d, cands, {}, exact_max=8)]
    results += [v.elimination(k, ballots, cands, {}, o, 10) for k in v.ROUNDS
                for o in ("sequential", "elimination_order")]
    for r in results:
        assert sorted(r.order) == sorted(cands)


def test_footrule():
    assert v.footrule(["a", "b"], ["a", "b", "c"], 2) == 0
    assert v.footrule(["b", "a"], ["a", "b"], 2) == 2
    assert v.footrule(["c"], ["a"], 1) == 2  # both off the other's list: |1-2| + |2-1|


# ---- custom-ballot input validation --------------------------------------------------------

def test_custom_ballot_errors():
    with pytest.raises(ValueError):
        run({"ballots": [["a", "a"]]})
    with pytest.raises(ValueError):
        run({"ballots": [["a"], ["b"]], "weights": [1]})
    with pytest.raises(ValueError):
        run({})


def test_points_input_used_as_official():
    pred = run({"ballots": [["a", "b"], ["b", "a"], ["b", "a"]], "points": [1, 0]}, method="official")
    assert pred.primary.label == "Winner (Official points): b"


# ---- real data (skipped until `ballmonitor fetch ranked_choice` has built the source) -------

# BBWAA's own pages disagree (ballot page vs results table) for these; see sources/mlb.md
# College Poll Tracker is missing one ballot (or one place) in these AP weeks; see sources/ap_polls.md
KNOWN_MISMATCH = {"mlb-2012-al-mvp", "mlb-2012-nl-mvp", "mlb-2014-al-mvp", "mlb-2016-al-mvp",
                  "ap-cfb-2014-final", "ap-cfb-2019-final", "ap-mbb-2015-16-final", "ap-mbb-2016-17-final",
                  "ap-mbb-2017-18-final"}


def _contests(source):
    return data.contests(DATA, source)


@pytest.mark.parametrize("source", data.SOURCES)
def test_recomputed_official_points_match_published(source):
    rows = [r for r in _contests(source) if r.get("published") and r["contest_id"] not in KNOWN_MISMATCH]
    if not rows:
        pytest.skip(f"no published totals for {source}")
    rng = random.Random(0)
    for contest in rng.sample(rows, min(15, len(rows))):
        ballots_rows, _, _ = data.ballots_for(DATA, contest)
        pts = data.points_list(contest)
        score = {}
        for b in ballots_rows:
            for r, c in enumerate(b["ranking"]):
                score[c] = score.get(c, 0.0) + (pts[r] if r < len(pts) else 0.0)
        for cid, published, _ in data.published(contest):
            assert score.get(cid, 0.0) == pytest.approx(published), (contest["contest_id"], cid)


@pytest.mark.parametrize("source", data.SOURCES)
def test_ballots_are_well_formed(source):
    rows = _contests(source)
    if not rows:
        pytest.skip(f"no data for {source}")
    for contest in rows[-3:]:
        ballots_rows, names, _ = data.ballots_for(DATA, contest)
        assert len(ballots_rows) == int(contest["n_ballots"])
        for b in ballots_rows:
            assert len(b["ranking"]) == len(set(b["ranking"])) <= int(contest["n_places"])
        assert all(names.get(c) for b in ballots_rows for c in b["ranking"])


def test_latest_resolves():
    if not _contests("ap_cfb"):
        pytest.skip("no AP football data")
    pred = run({"contest": "ap-cfb-latest"})
    assert pred.extras["n_places"] == 25 and pred.extras["n_ballots"] >= 50
    assert len([o for o in pred.outcomes if o.group.startswith("Ranking")]) == 25


def test_default_example_known_values():
    if not _contests("mlb"):
        pytest.skip("no MLB data")
    pred = run(registry.load_example("ranked_choice", "default"))
    ex = pred.extras
    off = ex["orders"]["official"]
    assert ex["candidates"][off[0]]["name"] == "David Price"
    assert ex["candidates"][off[0]]["official_points"] == 153
    assert ex["candidates"][off[1]]["official_points"] == 149
    assert ex["condorcet_winner"] is None and ex["n_ballots"] == 28


# Published PHWA results (news reports of the official tallies); the PDFs have no totals table.
NHL_PUBLISHED = {
    ("nhl-2017-18-hart", "taylor-hall"): (1264, [72, 62, 19, 4, 3]),
    ("nhl-2017-18-hart", "nathan-mackinnon"): (1194, [60, 66, 19, 11, 4]),
    ("nhl-2021-22-norris", "cale-makar"): (1631, [92, 98, 5, 0, 0]),
    ("nhl-2021-22-norris", "roman-josi"): (1606, [98, 76, 17, 3, 0]),
    ("nhl-2024-25-hart", "connor-hellebuyck"): (1346, None),
    ("nhl-2024-25-hart", "leon-draisaitl"): (1209, None),
    ("nhl-2025-26-hart", "nikita-kucherov"): (1436, None),
    ("nhl-2025-26-hart", "connor-mcdavid"): (1426, None),
}


@pytest.mark.parametrize("contest_id,candidate", list(NHL_PUBLISHED))
def test_nhl_matches_published_results(contest_id, candidate):
    if not _contests("nhl") or not any(c["n_ballots"] != "0" for c in _contests("nhl")):
        pytest.skip("no NHL ballots (PDFs are downloaded by the user)")
    contest = data.resolve(DATA, contest_id)
    rows, _, _ = data.ballots_for(DATA, contest)
    places = [0] * 5
    for b in rows:
        if candidate in b["ranking"]:
            places[b["ranking"].index(candidate)] += 1
    points, counts = NHL_PUBLISHED[(contest_id, candidate)]
    assert sum(p * k for p, k in zip([10, 7, 5, 3, 1], places)) == points
    if counts:
        assert places == counts


def test_norris_2022_condorcet_winner_is_josi():
    if not any(c["n_ballots"] != "0" for c in _contests("nhl")):
        pytest.skip("no NHL ballots")
    ex = run({"contest": "nhl-2021-22-norris"}).extras
    assert ex["orders"]["official"][0] == "cale-makar"
    assert ex["condorcet_winner"] == "roman-josi"
