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
