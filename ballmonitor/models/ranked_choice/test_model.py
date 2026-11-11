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


def test_fptp_place_by_place_and_ties_kept():
    """Tennessee: Memphis has the most first places (42); without Memphis its ballots go to
    Nashville (42 + 26 = 68); then Chattanooga (83); Knoxville last."""
    r = v.fptp(TENNESSEE, CANDS, {})
    assert r.order == [M, N, C, K] and r.ranks == {M: 1, N: 2, C: 3, K: 4}
    assert r.scores == {M: 42.0, N: 68.0, C: 83.0, K: 100.0}
    # A and B tie on first places (2 each); B has a second place, A none. Plurality uses the
    # second places, FPTP doesn't: they share 1st and leave together, C is 3rd.
    ballots = [["A", "C"], ["A", "C"], ["B", "C"], ["B", "C"], ["C", "B"]]
    cands = ["A", "B", "C"]
    assert v.plurality(ballots, cands, {}).order[0] == "B"
    f = v.fptp(ballots, cands, {"A": (1,), "B": (0,)})
    assert f.ranks == {"A": 1, "B": 1, "C": 3} and f.order[0] == "A"   # list order: shared tie-break


def test_top_two_runoff_place_by_place():
    """Tennessee: Memphis (42) and Nashville (26) meet; Nashville wins 58-42. Then Memphis (42)
    vs Chattanooga (41): Chattanooga 58-42; then Knoxville beats Memphis; Memphis last."""
    d = v.pairwise(TENNESSEE, CANDS)
    r = v.top_two(TENNESSEE, CANDS, d, {})
    assert r.order == [N, C, K, M]
    assert r.scores[N] == 58.0
    # one candidate: no runoff
    assert v.top_two([["A"]], ["A"], v.pairwise([["A"]], ["A"]), {}).order == ["A"]


def test_fptp_on_the_site_page():
    from ballmonitor.models.ranked_choice import site

    ex = run({"contest": "mlb-2023-nl-moy"}, compare_methods=site.METHODS).extras
    # 2023 NL Manager of the Year: Schumaker won on points; he and Snitker had 8 first places each
    assert site._fptp_winner(ex) == "Skip Schumaker / Brian Snitker (tied)"


def test_site_page_builds_cleanly():
    from ballmonitor.core import views
    from ballmonitor.models.ranked_choice import site

    page = site.page(registry.load_model("ranked_choice"))
    assert views.check(page) == []
    flips = next(v for v in page["views"] if v["id"] == "award_flips")
    assert any(r["award"] == "NBA Defensive Player of the Year" and r["season"] == "2014-15" for r in flips["rows"])


# ---- AP fetch: new weeks are found even when the latest week's ballots are not posted yet ---

def test_ap_fetch_finds_weeks_before_an_unposted_latest_week(tmp_path, monkeypatch):
    """CI case: no raw cache, built CSV ends at week 8, the site's latest poll is week 10 but
    its grid has no ballots yet. Week 9 (listed on the rankings page) must still be fetched."""
    from ballmonitor.models.ranked_choice.sources import ap_polls as ap

    def opts(name, vals, sel):
        mark = {sel: ' selected="selected"'}
        o = "".join(f'<option value="{v}"{mark.get(v, "")}>{v}</option>' for v in vals)
        return f'<select name="{name}">{o}</select>'

    weeks = ["week-10", "week-9", "week-8", "pre-season"]
    rankings = opts("year", ["2026"], "2026") + opts("week", weeks, "week-10")
    grid9 = opts("year", ["2026"], "2026") + opts("week", weeks, "week-9") + '<div class="gridRow">'
    calls = []

    def fake_get(url, log=print):
        calls.append(url)
        if url == f"{ap.BASE}/football/":
            return 302, f"{ap.BASE}/football/2026/week-10", rankings
        if url.endswith("/grid/2026/week-9"):
            return 200, "", grid9
        if url.endswith("/grid/2026/week-10"):
            return 200, "", "<html>ballots coming soon</html>"
        return 404, "", ""

    monkeypatch.setattr(ap, "_get", fake_get)
    have = {ap.contest_id("football", 2026, w) for w in ("pre-season", "week-8")}
    lines = []
    ap._download_sport(tmp_path, "football", lines.append, have)
    assert (tmp_path / "football" / "2026" / "week-9.html").exists()
    assert not (tmp_path / "football" / "2026" / "week-10.html").exists()
    assert not any(u.endswith("/grid/2026/week-8") for u in calls)  # already built
    assert any("no ballots posted yet" in s for s in lines)


def test_fetch_passes_on_top_level_source_lines(tmp_path, monkeypatch):
    from ballmonitor.models.ranked_choice import fetch as f
    from ballmonitor.models.ranked_choice.sources import ap_polls as ap

    def fake(model_dir, offline=False, log=print):
        log("STOPPED: answered 429")
        log("  GET detail")
        return ["x.csv.gz"]

    monkeypatch.setattr(ap, "fetch", fake)
    monkeypatch.setattr(f, "SOURCES", ["ap_polls"])
    out = list(f.fetch(tmp_path))
    assert out == ["ap_polls: STOPPED: answered 429", "ap_polls: x.csv.gz"]


def test_poll_headline_says_this_week_only_while_the_poll_is_current():
    import datetime as dt

    from ballmonitor.models.ranked_choice import site
    today = dt.date(2026, 11, 10)
    assert site._current("2026-11-08", "college football, Week 10", today)
    assert not site._current("2026-10-25", "college football, Week 8", today)       # stale data
    assert not site._current("2026-11-08", "college football, Final", today)        # off-season
    assert not site._current("", "men's basketball, Week 1", today)


def test_mlb_fetch_without_saved_pages_keeps_built_awards_and_asks_only_for_new_ones(tmp_path, monkeypatch):
    """The daily CI build has no data/raw: in November it reads the two sitemaps, keeps every award
    already built and would ask only for a new award's pages; in other months it asks for nothing."""
    import datetime as dt
    import gzip
    import shutil

    from ballmonitor.models.ranked_choice.sources import mlb
    src = Path(__file__).parent / "data" / "ballots"
    if not (src / "mlb.csv.gz").exists():
        pytest.skip("no built MLB ballots")
    out = tmp_path / "data" / "ballots"
    out.mkdir(parents=True)
    for name in ("mlb.csv.gz", "mlb_contests.csv.gz"):
        shutil.copy2(src / name, out / name)
    before = {n: gzip.open(out / n).read() for n in ("mlb.csv.gz", "mlb_contests.csv.gz")}
    asked = []

    def get(self, slug, fname, refresh=False):
        asked.append(slug)
        if slug.endswith(".xml"):   # the sitemap lists one award that is already built
            return "https://bbwaa.com/24-al-mvp/ https://bbwaa.com/24-al-mvp-ballots/" if slug.startswith("post") else ""
        raise AssertionError(f"asked for a page of an award that is already built: {slug}")

    monkeypatch.setattr(mlb._Fetcher, "get", get)
    monkeypatch.setattr(mlb, "SLUG_OVERRIDES", {})
    assert mlb.fetch(tmp_path, log=lambda *_: None, today=dt.date(2026, 6, 1)) == [] and asked == []
    written = mlb.fetch(tmp_path, log=lambda *_: None, today=dt.date(2026, 11, 12))
    assert sorted(asked) == ["page-sitemap.xml", "post-sitemap.xml"] and len(written) == 2
    assert {n: gzip.open(out / n).read() for n in before} == before   # nothing lost, nothing reordered
