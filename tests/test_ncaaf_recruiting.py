import os
import pytest
from pathlib import Path

from ballmonitor.models.ncaaf_recruiting.src.data_loader import DataLoader
from ballmonitor.models.ncaaf_recruiting.src.elo_engine import EloEngine
from ballmonitor.models.ncaaf_recruiting.src.geocoding import (
    CityLocator,
    get_campus_coords,
    haversine_miles,
    pure_levenshtein_distance,
)
from ballmonitor.models.ncaaf_recruiting.src.models import RankingMethod, Recruit
from ballmonitor.models.ncaaf_recruiting.src.forecasting import CommitmentPredictor, SigningDayForecaster
from ballmonitor.models.ncaaf_recruiting.src.position_model import (
    DEFAULT_POSITION_WEIGHTS,
    PositionalRankingEngine,
    PositionWeight,
)
from ballmonitor.models.ncaaf_recruiting.src.scrapers.on3 import On3Scraper, standardize_team_name


def test_pure_levenshtein_distance():
    assert pure_levenshtein_distance("Austin", "Austin") == 0
    assert pure_levenshtein_distance("Austin", "Austn") == 1
    assert pure_levenshtein_distance("Athens", "Atlanta") == 4


def test_campus_coordinates_and_distance():
    bama_coords = get_campus_coords("Alabama")
    assert bama_coords is not None
    # Tuscaloosa to Auburn is ~130 miles
    auburn_coords = get_campus_coords("Auburn")
    assert auburn_coords is not None
    dist = haversine_miles(bama_coords, auburn_coords)
    assert 120 < dist < 140


def test_data_loader_recruits():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2021, geolocate=True)
    assert len(recruits) > 3000
    r0 = recruits[0]
    assert r0.year == 2021
    assert r0.committed_team != ""
    assert isinstance(r0.offers, list)


def test_plackett_luce_engine_run():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2021, geolocate=True)
    engine = EloEngine(method=RankingMethod.PLACKETT_LUCE)
    result = engine.run(2021, recruits)

    assert result.year == 2021
    assert result.method == RankingMethod.PLACKETT_LUCE
    assert len(result.teams) > 100

    # Alabama and Ohio State should be top 3 for 2021
    top_3_names = [t.name for t in result.teams[:3]]
    assert "Alabama" in top_3_names
    assert "Ohio State" in top_3_names

    # Scores should be monotonically non-increasing
    for i in range(len(result.teams) - 1):
        assert result.teams[i].total_score >= result.teams[i + 1].total_score

    # Top teams should have geographic distance stats
    bama = result.by_name["alabama"]
    assert bama.avg_recruit_distance > 0
    assert bama.national_pct > 0


def test_sequential_elo_engine_run():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2021)
    engine = EloEngine(method=RankingMethod.SEQUENTIAL_ELO)
    result = engine.run(2021, recruits)

    assert result.year == 2021
    assert result.method == RankingMethod.SEQUENTIAL_ELO
    assert len(result.teams) > 100
    assert "Alabama" in [t.name for t in result.teams[:5]]


def test_team_name_aliases_merge_sources():
    from ballmonitor.models.ncaaf_recruiting.src.data_loader import normalize_team

    assert normalize_team("USF") == normalize_team("South Florida") == "South Florida"
    assert normalize_team("Florida International") == normalize_team("FIU") == "FIU"
    assert normalize_team("UT San Antonio") == "UTSA"


def test_engine_fit_recruits_scores_only_current_class():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    cur, prev = loader.load_recruits(2024), loader.load_recruits(2023)
    engine = EloEngine()
    base = engine.run(2024, cur)
    pooled = engine.run(2024, cur, fit_recruits=cur + prev)
    assert sum(t.commits_count for t in base.teams) == sum(t.commits_count for t in pooled.teams)
    assert {t.name for t in pooled.teams} == {t.name for t in base.teams}


def test_standardize_team_name():
    assert standardize_team_name("Miami", "miami-hurricanes") == "Miami (FL)"
    assert standardize_team_name("Miami", "miami-oh-redhawks") == "Miami (OH)"
    assert standardize_team_name("Ohio State", "ohio-state-buckeyes") == "Ohio State"
    assert standardize_team_name("Georgia", "georgia-bulldogs") == "Georgia"


@pytest.mark.skipif(
    not os.environ.get("BALLMONITOR_NETWORK_TESTS"),
    reason="hits on3.com over the network; set BALLMONITOR_NETWORK_TESTS=1 to run",
)
def test_on3_scraper_fetch_sample():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    scraper = On3Scraper(city_locator=loader._get_locator())
    sample = scraper.fetch_recruits(year=2024, limit=2)
    assert len(sample) == 2
    r0 = sample[0]
    assert r0.name == "Jeremiah Smith"
    assert r0.year == 2024
    assert r0.committed_team == "Ohio State"
    assert len(r0.offers) >= 15
    assert "Miami (FL)" in r0.offers
    assert r0.stars == 5
    assert r0.latitude > 0 and r0.longitude < 0


def test_positional_ranking_engine_consistency():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2024)
    engine = EloEngine()
    result = engine.run(2024, recruits)

    pos_engine = PositionalRankingEngine()
    pos_result = pos_engine.evaluate(result)

    assert pos_result.year == 2024
    assert len(pos_result.teams) > 50

    for t in pos_result.teams[:20]:
        # Sum consistency: Run Offense + Pass Offense == Offense
        assert abs((t.run_offense_score + t.pass_offense_score) - t.offense_score) < 1e-4
        # Sum consistency: Run Defense + Pass Defense == Defense
        assert abs((t.run_defense_score + t.pass_defense_score) - t.defense_score) < 1e-4
        # Offense + Defense should be positive for teams with commits
        if t.commits_count > 0:
            assert t.offense_score + t.defense_score > 0

    # Test sorting by unit
    off_ranked = pos_result.rank_by("offense")
    for i in range(len(off_ranked) - 1):
        assert off_ranked[i].offense_score >= off_ranked[i + 1].offense_score

    def_ranked = pos_result.rank_by("defense")
    for i in range(len(def_ranked) - 1):
        assert def_ranked[i].defense_score >= def_ranked[i + 1].defense_score

    pass_off_ranked = pos_result.rank_by("pass_offense")
    for i in range(len(pass_off_ranked) - 1):
        assert pass_off_ranked[i].pass_offense_score >= pass_off_ranked[i + 1].pass_offense_score


def test_position_weight_defaults():
    qb = DEFAULT_POSITION_WEIGHTS["QB"]
    assert qb.offense_share == 1.0
    assert qb.defense_share == 0.0
    assert qb.run_pct + qb.pass_pct == 1.0

    dt = DEFAULT_POSITION_WEIGHTS["DT"]
    assert dt.offense_share == 0.0
    assert dt.defense_share == 1.0
    assert dt.run_pct + dt.pass_pct == 1.0

    ath = DEFAULT_POSITION_WEIGHTS["ATH"]
    assert ath.offense_share == 0.5
    assert ath.defense_share == 0.5


def test_commitment_predictor_probabilities():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2026, geolocate=True, include_uncommitted=True)
    commits = [r for r in recruits if r.committed_team and r.committed_team != "0"]

    engine = EloEngine()
    res = engine.run(2026, commits)
    team_ratings = {t.name: t for t in res.teams}

    predictor = CommitmentPredictor(team_ratings=team_ratings, distance_decay=0.85)

    # Test dummy recruit in Atlanta with offers from Georgia, Alabama, Ohio State, USC
    atlanta_recruit = Recruit(
        url="",
        year=2026,
        name="TEST RECRUIT",
        position="WR",
        hometown="Atlanta, GA",
        stars=5,
        committed_team="",
        offers=["Georgia", "Alabama", "Ohio State", "USC"],
        latitude=33.7490,
        longitude=-84.3880,
    )

    probs = predictor.predict_probabilities(atlanta_recruit)
    assert len(probs) == 4
    assert abs(sum(probs.values()) - 1.0) < 1e-4

    # Georgia (closest, ~65 mi) should have highest probability
    assert probs["Georgia"] > probs["USC"]
    assert probs["Georgia"] > probs["Ohio State"]


def test_signing_day_forecaster_and_scenario_override():
    loader = DataLoader(Path("ballmonitor/models/ncaaf_recruiting/data"))
    recruits = loader.load_recruits(2026, geolocate=True, include_uncommitted=True)

    forecaster = SigningDayForecaster()
    # Run small simulation
    fc_res = forecaster.forecast(2026, recruits, n_simulations=50, seed=42)

    assert fc_res.year == 2026
    assert len(fc_res.teams) > 50
    assert fc_res.unsigned_count > 0

    top_team = fc_res.teams[0]
    assert top_team.projected_score_mean >= top_team.current_score
    assert 0.0 <= top_team.prob_top1 <= 1.0

    # Test what-if scenario override
    scenario = forecaster.compare_scenarios(
        year=2026,
        recruits=recruits,
        scenario_overrides={"JONTAVIUS WYMAN": "Ole Miss"},
        n_simulations=50,
    )

    assert len(scenario.deltas) > 0
    ole_miss_delta = next((d for d in scenario.deltas if d.team == "Ole Miss"), None)
    assert ole_miss_delta is not None
    assert ole_miss_delta.score_delta >= 0.0


def test_mbb_and_wbb_unified_recruiting_model():
    from ballmonitor.core import registry
    model = registry.load_model("ncaaf_recruiting")

    mbb_pred = model.predict({"sport": "mbb", "year": 2025, "team": "Duke"})
    assert mbb_pred.primary.estimate > 0
    assert mbb_pred.extras["sport"] == "mbb"
    assert len(mbb_pred.extras["rankings"]) >= 20

    wbb_pred = model.predict({"sport": "wbb", "year": 2026, "team": "Notre Dame"})
    assert wbb_pred.primary.estimate > 0
    assert wbb_pred.extras["sport"] == "wbb"
    assert len(wbb_pred.extras["rankings"]) >= 20


# --------------------------------------------------------------- men's basketball (v0.5.0)

def test_mbb_school_names_map_to_barttorvik():
    from ballmonitor.models.ncaaf_recruiting.src.mbb_names import to_bart

    known = {"Ohio St.", "Gonzaga", "Miami FL", "N.C. State", "UT Arlington", "Long Beach St.",
             "Notre Dame", "Saint Mary's", "Duke"}
    assert to_bart("Ohio State", known) == "Ohio St."
    assert to_bart("Gonzaga University", known) == "Gonzaga"
    assert to_bart("Miami (FL)", known) == "Miami FL"
    assert to_bart("NC State", known) == "N.C. State"
    assert to_bart("The University of Texas at Arlington", known) == "UT Arlington"
    assert to_bart("California State University-Long Beach", known) == "Long Beach St."
    assert to_bart("Saint Mary's College of California", known) == "Saint Mary's"
    assert to_bart("Duke", known) == "Duke"
    # a different (non-D-I) school must not collapse onto a D-I name
    assert to_bart("Notre Dame College", known) == ""
    assert to_bart("NBA G League", known) == ""


def test_mbb_player_name_key():
    from ballmonitor.models.ncaaf_recruiting.src.mbb_names import last_name, player_key

    assert player_key("D'Angelo Russell Jr.") == player_key("DAngelo Russell") == "dangelo russell"
    assert player_key("R.J. Barrett") == player_key("RJ Barrett")
    assert player_key("Marvin Bagley III") == "marvin bagley"
    assert player_key("Nick Smith Jr.") == player_key("Nicholas Smith")
    assert player_key("Moussa Cissé") == "moussa cisse"
    assert last_name("Dereck Lively II") == "lively"


def test_fetch_commit_priority_and_page_dedupe(tmp_path):
    import json

    from ballmonitor.models.ncaaf_recruiting import fetch

    def item(status, name):
        return {"status": status, "team": {"name": name, "slug": name.lower()}}

    committed, status, offers = fetch._commit_and_offers(
        [item("Signed", "Kennesaw State"), item("Offered", "Auburn"), item("Enrolled", "Louisville")])
    assert (committed, status) == ("Louisville", "Enrolled")
    assert offers == ["Auburn", "Kennesaw State"]  # the released signee school competed

    raw = tmp_path / "on3"
    (raw / "players").mkdir(parents=True)
    page = lambda keys: {"pagination": {"pageCount": 2}, "list": [{"person": {"key": k}} for k in keys]}
    (raw / "players" / "mbb_2015_p1.json").write_text(json.dumps(page([1, 2, 3])))
    (raw / "players" / "mbb_2015_p2.json").write_text(json.dumps(page([3, 4])))
    players = fetch._players(raw, "mbb", 2015, offline=True)
    assert [p["person"]["key"] for p in players] == [1, 2, 3, 4]


def test_mbb_history_classes_and_non_college_destinations():
    from ballmonitor.models.ncaaf_recruiting.model import available_years

    data = Path("ballmonitor/models/ncaaf_recruiting/data")
    assert set(range(2014, 2028)) <= set(available_years(data, "mbb"))
    loader = DataLoader(data)
    recruits = loader.load_recruits(2021, sport="mbb")
    teams = {r.committed_team for r in recruits} | {t for r in recruits for t in r.offers}
    assert "NBA G League" not in teams and "Professional" not in teams
    result = EloEngine(cornerstone_weight=0.25, quality_power=0.6, l2_reg=0.05, rank_decay=0.75).run(2021, recruits)
    assert "NBA G League" not in [t.name for t in result.teams]
    # no recruit appears twice in a class file
    for year in range(2014, 2028):
        urls = [r.url for r in loader.load_recruits(year, sport="mbb", include_uncommitted=True)]
        assert len(urls) == len(set(urls)), year


def test_barttorvik_player_columns_match_known_seasons():
    import csv

    path = Path("ballmonitor/models/ncaaf_recruiting/data/outcomes/mbb_player_seasons.csv")
    rows = {(r["name"], r["season"]): r for r in csv.DictReader(open(path, encoding="utf-8"))}
    zion = rows[("Zion Williamson", "2019")]
    assert zion["team"] == "Duke" and zion["class"] == "Fr"
    assert float(zion["pts"]) == pytest.approx(22.6, abs=0.1)
    assert float(zion["draft_pick"]) == 1
    cade = rows[("Cade Cunningham", "2021")]
    assert float(cade["pts"]) == pytest.approx(20.1, abs=0.2)


def test_research_mbb_partial_correlation_helpers():
    import numpy as np

    from ballmonitor.models.ncaaf_recruiting import research_mbb as R

    rng = np.random.default_rng(0)
    z = rng.normal(size=2000)
    x = z + 0.1 * rng.normal(size=2000)  # x is z plus noise: nothing beyond z
    y = z + rng.normal(size=2000)
    assert R._spearman(x, y) > 0.5
    assert abs(R._partial(x, y, z)) < 0.06
    w = rng.normal(size=2000)
    assert R._partial(w + 0 * z, w + z, z) > 0.5  # independent information is kept
    pct = R.pct_within([1.0, 2.0, 3.0, 10.0, 20.0], [1, 1, 1, 2, 2])
    assert list(pct) == pytest.approx([1 / 3, 2 / 3, 1.0, 0.5, 1.0])


# ------------------------------------------------------------ scheduled (daily CI) update

def _fake_on3(tmp_path, n=14, csv_keys=range(1, 14), counts=None, list_fails=False, cfg=""):
    """A model dir with a committed 2027 file + manifest + benchmark, and a fake On3 that
    lists recruits 1..n (2 per page) and answers team-targets. No network."""
    import csv as _csv

    from ballmonitor.models.ncaaf_recruiting import fetch

    rec = tmp_path / "data" / "recruits"
    bench = tmp_path / "data" / "benchmarks"
    rec.mkdir(parents=True)
    bench.mkdir(parents=True)
    (tmp_path / "config.toml").write_text(cfg)
    teams = {k: ("Alabama" if k % 3 == 0 else "" if k % 5 == 0 else "Georgia") for k in range(1, 30)}
    with open(rec / "football2027done.csv", "w", newline="") as fh:
        for k in csv_keys:
            _csv.writer(fh).writerow([f"https://www.on3.com/db/p-{k}/", 2027, f"P{k}", "QB", "X", 3,
                                      teams[k], "Old U"])
    with open(rec / "manifest.csv", "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["sport", "year", "file", "source", "status", "fetched", "rows", "commits", "offer_coverage"])
        w.writerow(["ncaaf", 2027, "football2027done.csv", "On3", "in_progress", "2026-11-01", 13, 10, 1.0])
        w.writerow(["mbb", 2027, "recruits_mbb_2027.csv", "On3", "in_progress", "2026-11-01", 5, 5, 1.0])
    old = counts or {"Alabama": 4, "Georgia": 7}
    with open(bench / "consensus_team_rankings.csv", "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["sport", "year", "rank", "team", "consensus_points", "commits", "five_stars", "four_stars"])
        w.writerow(["ncaaf", 2026, 1, "Texas", 90.0, 25, 1, 1])
        for i, (t, c) in enumerate(old.items(), 1):
            w.writerow(["ncaaf", 2027, i, t, 90.0, c, 0, 0])
    calls = []

    def opener(url):
        calls.append(url)
        if "industry-comparision" in url:
            if list_fails:
                raise OSError("On3 down")
            page = int(url.rsplit("page=", 1)[1])
            keys = [k for k in range(2 * page - 1, 2 * page + 1) if k <= n]
            return {"pagination": {"pageCount": -(-n // 2)},
                    "list": [{"person": {"key": k, "name": f"P{k}", "slug": f"p-{k}"}, "ratings": []} for k in keys]}
        if "consensus-team-rankings" in url:
            return {"pagination": {"pageCount": 1}, "list": [
                {"overallConsensusRank": 1, "organization": {"name": "Alabama"}, "commits": 5},
                {"overallConsensusRank": 2, "organization": {"name": "Georgia"}, "commits": 7}]}
        key = int(url.split("/player/")[1].split("/")[0])
        return {"pagination": {"pageCount": 1}, "list": [
            {"status": "Committed", "team": {"name": "Alabama"}}, {"status": "Offered", "team": {"name": "New U"}}]}

    return fetch, opener, calls


def _class_rows(tmp_path):
    import csv as _csv

    with open(tmp_path / "data" / "recruits" / "football2027done.csv", newline="") as fh:
        return {int(r[0].rstrip("/").rsplit("-", 1)[1]): r for r in _csv.reader(fh)}


def test_scheduled_selection_order_quota_and_today():
    from ballmonitor.models.ncaaf_recruiting.fetch import select_targets

    known = {1: {"committed": "A", "date": "2026-11-01"}, 2: {"committed": "", "date": "2026-11-01"},
             3: {"committed": "B", "date": "2026-11-10"}, 4: {"committed": "B", "date": "2026-11-05"},
             5: {"committed": "A", "date": "2026-11-20"}, **{k: {"committed": "C", "date": "2026-11-15"}
                                                              for k in range(6, 15)}}
    keys = list(range(1, 16))  # 15 is new
    picked = select_targets(keys, known, {"A"}, True, "2026-11-20", refresh_days=5)
    assert picked[:3] == [(15, "new"), (1, "program's commit count moved"), (2, "uncommitted")]
    assert 5 not in [k for k, _ in picked]  # read today already (A changed, still skipped)
    # quota ceil(15/5) = 3, minus 1 read today, minus 3 picked: no rotation today
    assert [r for _, r in picked].count("rotation") == 0
    picked = select_targets(keys, known, set(), False, "2026-11-20", refresh_days=1)
    assert picked[0] == (15, "new")
    rotation = [k for k, r in picked if r == "rotation"]
    # stalest first (1 and 2 tie on 11-01, then 4, then 3), everyone but 5 (read today)
    assert set(rotation[:2]) == {1, 2} and rotation[2:4] == [4, 3] and len(rotation) == 13


def test_scheduled_update_cold_cache_cap_and_second_run(tmp_path):
    import json

    fetch, opener, calls = _fake_on3(tmp_path)
    # 7 list pages + 1 ranking page + 4 target reads
    get = fetch.PoliteGetter(12, opener=opener)
    lines = fetch.scheduled_update(tmp_path, get=get, today="2026-11-20")
    assert get.used == 12 and len(calls) == 12, lines
    targets = [int(u.split("/player/")[1].split("/")[0]) for u in calls if "/player/" in u]
    # new recruit first, then recruits committed to Alabama (its count moved 4 -> 5)
    assert targets == [14, 3, 6, 9]
    rows = _class_rows(tmp_path)
    assert len(rows) == 14
    assert rows[14][6:] == ["Alabama", "New U"] and rows[3][6:] == ["Alabama", "New U"]
    assert rows[1][6:] == ["Georgia", "Old U"] and rows[12][6:] == ["Alabama", "Old U"]  # kept from the CSV
    manifest = (tmp_path / "data" / "recruits" / "manifest.csv").read_text().splitlines()
    assert manifest[1].startswith("ncaaf,2027,football2027done.csv,On3,in_progress,2026-11-20,14,")
    assert manifest[2].endswith("2026-11-01,5,5,1.0")  # other rows untouched
    bench = (tmp_path / "data" / "benchmarks" / "consensus_team_rankings.csv").read_text()
    assert "ncaaf,2027,1,Alabama,0.0,5,0,0" in bench and "ncaaf,2026,1,Texas" in bench
    state = json.loads((tmp_path / "data" / "raw" / "scheduled" / "on3_ncaaf_2027.json").read_text())
    assert set(state["recruits"]) == {"14", "3", "6", "9"} and state["team_commits"]["Alabama"] == 5

    # warm cache, same day: counts match the state now, recruits read today are skipped,
    # and the daily quota (ceil(14 / refresh_days 14) = 1) is used up: only the list + ranking pages.
    calls.clear()
    fetch.scheduled_update(tmp_path, get=fetch.PoliteGetter(600, opener=opener), today="2026-11-20")
    assert not [u for u in calls if "/player/" in u]
    # next day: rotation picks the stalest 1 (from the CSV), never the ones read yesterday
    calls.clear()
    fetch.scheduled_update(tmp_path, get=fetch.PoliteGetter(600, opener=opener), today="2026-11-21")
    targets = [int(u.split("/player/")[1].split("/")[0]) for u in calls if "/player/" in u]
    assert len(targets) == 1 and not set(targets) & {14, 3, 6, 9}


def test_scheduled_update_keeps_files_when_on3_fails(tmp_path):
    fetch, opener, _ = _fake_on3(tmp_path, list_fails=True)
    path = tmp_path / "data" / "recruits" / "football2027done.csv"
    before = path.read_text(), (tmp_path / "data" / "recruits" / "manifest.csv").read_text()
    lines = fetch.scheduled_update(tmp_path, get=fetch.PoliteGetter(600, opener=opener, tries=2),
                                   today="2026-11-20")
    assert "kept the committed files" in lines[-1]
    assert (path.read_text(), (tmp_path / "data" / "recruits" / "manifest.csv").read_text()) == before
    # a list much shorter than the file (On3 half-answering) is refused too
    fetch, opener, _ = _fake_on3(tmp_path / "short", n=6, csv_keys=range(1, 14))
    lines = fetch.scheduled_update(tmp_path / "short", get=fetch.PoliteGetter(600, opener=opener),
                                   today="2026-11-20")
    assert "kept the committed files" in lines[-1]


def test_update_and_build_passes_scheduled_only_to_fetches_that_take_it():
    from ballmonitor import cli

    class Full:
        @staticmethod
        def fetch(d, offline=False):
            return ["full"]

    class Light:
        @staticmethod
        def fetch(d, offline=False, scheduled=False):
            return ["light" if scheduled else "full"]

    assert cli._run_fetch(Full, Path("."), False, True) == ["full"]
    assert cli._run_fetch(Light, Path("."), False, True) == ["light"]
    assert cli._run_fetch(Light, Path("."), False, False) == ["full"]
