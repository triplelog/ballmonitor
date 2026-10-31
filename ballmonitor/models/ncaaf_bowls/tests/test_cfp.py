import pytest
from ballmonitor.models.ncaaf_bowls.cfp import CFPSelector
from ballmonitor.models.ncaaf_bowls.domain import Bowl, Team, TeamSimState

def create_mock_state(team_id: str, conf: str, rating: float, is_conf_champ: bool, resume_score: float) -> TeamSimState:
    t = Team(
        id=team_id,
        name=team_id.title(),
        conf=conf,
        rating=rating,
        apr=980,
        brand=8,
        city="",
        state="",
        lat=0.0,
        lon=0.0,
        wins=10,
        losses=2,
        conf_wins=7,
        conf_losses=1
    )
    s = TeamSimState(team=t, wins=10, losses=2, conf_wins=7, conf_losses=1, is_conf_champ=is_conf_champ)
    s.resume_score = resume_score
    return s

def test_12_team_playoff_selection():
    # Construct 16 teams: 6 conference champions + at-large candidates + Notre Dame
    states = {
        "sec_champ": create_mock_state("sec_champ", "SEC", 25.0, True, 95.0),
        "b10_champ": create_mock_state("b10_champ", "Big Ten", 26.0, True, 96.0),
        "acc_champ": create_mock_state("acc_champ", "ACC", 20.0, True, 88.0),
        "b12_champ": create_mock_state("b12_champ", "Big 12", 18.0, True, 86.0),
        "mwc_champ": create_mock_state("mwc_champ", "MWC", 14.0, True, 78.0),
        "aac_champ": create_mock_state("aac_champ", "AAC", 12.0, True, 74.0),
        "notre_dame": create_mock_state("notre_dame", "Independent", 22.0, False, 90.0),
        "sec_at_large1": create_mock_state("sec_at_large1", "SEC", 22.0, False, 89.0),
        "b10_at_large1": create_mock_state("b10_at_large1", "Big Ten", 21.0, False, 87.0),
        "sec_at_large2": create_mock_state("sec_at_large2", "SEC", 19.0, False, 85.0),
        "b10_at_large2": create_mock_state("b10_at_large2", "Big Ten", 18.0, False, 84.0),
        "acc_at_large1": create_mock_state("acc_at_large1", "ACC", 17.0, False, 82.0),
        "b12_at_large1": create_mock_state("b12_at_large1", "Big 12", 16.0, False, 80.0),
        "bubble_team1": create_mock_state("bubble_team1", "SEC", 15.0, False, 76.0),
        "bubble_team2": create_mock_state("bubble_team2", "Big Ten", 14.0, False, 75.0),
        "bubble_team3": create_mock_state("bubble_team3", "Big 12", 13.0, False, 70.0),
    }

    selector = CFPSelector({b.id: b for b in _bowls() if b.is_cfp})
    res = selector.select_and_seed(states)

    assert len(res.seeds) == 12
    assert len(res.cfp_team_ids) == 12

    # 2026 straight seeding: seeds follow the ranking; the top 4 get byes, champion or not
    scores = [s.resume_score for s in res.seeds]
    assert scores == sorted(scores, reverse=True)
    assert [s.cfp_bye for s in res.seeds] == [True] * 4 + [False] * 8
    nd = next(s for s in res.seeds if s.id == "notre_dame")
    assert nd.cfp_seed == 3 and nd.cfp_bye  # independent, ranked 3rd -> bye

    # Automatic bids: P4 champions + the highest-ranked Group-of-6 champion only
    assert {"sec_champ", "b10_champ", "acc_champ", "b12_champ", "mwc_champ"} <= res.cfp_team_ids
    assert "aac_champ" not in res.cfp_team_ids  # lower-ranked G6 champion, not at-large quality

    # #5 hosts #12, #6 hosts #11, #7 hosts #10, #8 hosts #9
    assert len(res.first_round) == 4
    assert res.first_round[0][0].cfp_seed == 5
    assert res.first_round[0][1].cfp_seed == 12


def test_low_ranked_power_champion_still_gets_auto_bid():
    states = {f"al{i}": create_mock_state(f"al{i}", "SEC", 20.0, False, 90.0 - i) for i in range(12)}
    states["acc_champ"] = create_mock_state("acc_champ", "ACC", 5.0, True, 40.0)
    res = CFPSelector({b.id: b for b in _bowls() if b.is_cfp}).select_and_seed(states)
    assert "acc_champ" in res.cfp_team_ids and res.seeds[-1].id == "acc_champ"


def _bowls():
    import json
    from ballmonitor.models.ncaaf_bowls.config import DATA_DIR
    return [Bowl.from_dict(d) for d in json.loads((DATA_DIR / "bowls.json").read_text())]
