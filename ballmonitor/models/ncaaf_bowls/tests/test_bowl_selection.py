import random
import pytest
from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.domain import Bowl, Team, TeamSimState
from ballmonitor.models.ncaaf_bowls.selection import BowlSelector

def test_bowl_selection_tie_ins():
    cfg = SimConfig()
    bowls = [
        Bowl(
            id="citrus_bowl",
            name="Cheez-It Citrus Bowl",
            city="Orlando", state="FL",
            lat=28.5, lon=-81.4,
            is_cfp=False,
            prestige=9, payout=8000000,
            slots=[{"confs": ["SEC"], "order": 1}, {"confs": ["Big Ten"], "order": 1}]
        ),
        Bowl(
            id="pop_tarts_bowl",
            name="Pop-Tarts Bowl",
            city="Orlando", state="FL",
            lat=28.5, lon=-81.4,
            is_cfp=False,
            prestige=8, payout=6000000,
            slots=[{"confs": ["ACC"], "order": 1}, {"confs": ["Big 12"], "order": 2}]
        ),
        Bowl(
            id="alamo_bowl",
            name="Valero Alamo Bowl",
            city="San Antonio", state="TX",
            lat=29.4, lon=-98.5,
            is_cfp=False,
            prestige=9, payout=8000000,
            slots=[{"confs": ["Big 12"], "order": 1}, {"confs": ["Pac-12 legacy"], "order": 1}]
        )
    ]

    teams = [
        Team("sec_1", "SEC Team 1", "SEC", 18.0, 980, 8, "City", "FL", 28.0, -82.0, 9, 3, 6, 2),
        Team("b10_1", "Big Ten Team 1", "Big Ten", 17.0, 980, 8, "City", "OH", 40.0, -83.0, 9, 3, 6, 2),
        Team("b12_1", "Big 12 Team 1", "Big 12", 15.0, 980, 7, "Austin", "TX", 30.0, -97.0, 9, 3, 6, 2),
        Team("b12_2", "Big 12 Team 2", "Big 12", 12.0, 980, 7, "Ames", "IA", 42.0, -93.0, 8, 4, 5, 3),
        Team("acc_1", "ACC Team 1", "ACC", 14.0, 980, 7, "Miami", "FL", 25.0, -80.0, 9, 3, 6, 2),
        Team("pac_1", "Pac-12 Team 1", "Pac-12", 11.0, 980, 6, "Pullman", "WA", 46.0, -117.0, 8, 4, 0, 0, legacy_pac12=True),
    ]

    states = {
        t.id: TeamSimState(team=t, wins=t.wins, losses=t.losses, conf_wins=t.conf_wins, conf_losses=t.conf_losses)
        for t in teams
    }

    selector = BowlSelector(bowls, teams, cfg)
    rng = random.Random(42)

    # CFP takes no teams here
    matchups = selector.select_bowls(states, cfp_team_ids=set(), rng=rng)

    matchup_dict = {m.bowl_id: m for m in matchups}

    # Citrus Bowl should have SEC and Big Ten
    citrus = matchup_dict["citrus_bowl"]
    teams_in_citrus = {citrus.team_1.id, citrus.team_2.id}
    assert "sec_1" in teams_in_citrus
    assert "b10_1" in teams_in_citrus

    # Alamo Bowl has Big 12 #1 (b12_1) and Pac-12 (pac_1)
    alamo = matchup_dict["alamo_bowl"]
    teams_in_alamo = {alamo.team_1.id, alamo.team_2.id}
    assert "b12_1" in teams_in_alamo
    assert "pac_1" in teams_in_alamo

    # Pop-Tarts has ACC (acc_1) and Big 12 #2 (b12_2)
    pop = matchup_dict["pop_tarts_bowl"]
    teams_in_pop = {pop.team_1.id, pop.team_2.id}
    assert "acc_1" in teams_in_pop
    assert "b12_2" in teams_in_pop

def test_anti_repeat_enforcement():
    cfg = SimConfig(bowl_temperature=0.0)
    bowls = [
        Bowl(
            id="citrus_bowl",
            name="Cheez-It Citrus Bowl",
            city="Orlando", state="FL",
            lat=28.5, lon=-81.4,
            is_cfp=False,
            prestige=9, payout=8000000,
            slots=[{"confs": ["SEC"], "order": 1}, {"confs": ["Big Ten"], "order": 1}]
        )
    ]

    # sec_repeat has better rating/brand/wins, but played in citrus_bowl last year
    sec_repeat = Team("sec_repeat", "SEC Repeat", "SEC", 20.0, 980, 10, "City", "FL", 28.5, -81.4, 10, 2, 7, 1, last_bowl="citrus_bowl")
    sec_fresh = Team("sec_fresh", "SEC Fresh", "SEC", 18.0, 980, 8, "City", "FL", 28.5, -81.4, 9, 3, 6, 2, last_bowl="gator_bowl")

    # b10_repeat has better record, but played in citrus_bowl last year
    b10_repeat = Team("b10_repeat", "Big Ten Repeat", "Big Ten", 19.0, 980, 9, "City", "OH", 40.0, -83.0, 10, 2, 7, 1, last_bowl="citrus_bowl")
    b10_fresh = Team("b10_fresh", "Big Ten Fresh", "Big Ten", 17.0, 980, 8, "City", "OH", 40.0, -83.0, 9, 3, 6, 2, last_bowl="reliaquest_bowl")

    teams = [sec_repeat, sec_fresh, b10_repeat, b10_fresh]
    states = {
        t.id: TeamSimState(team=t, wins=t.wins, losses=t.losses, conf_wins=t.conf_wins, conf_losses=t.conf_losses)
        for t in teams
    }

    selector = BowlSelector(bowls, teams, cfg)
    rng = random.Random(42)
    matchups = selector.select_bowls(states, cfp_team_ids=set(), rng=rng)
    citrus = {m.bowl_id: m for m in matchups}["citrus_bowl"]
    teams_in_citrus = {citrus.team_1.id, citrus.team_2.id}

    # Both fresh teams should be selected over repeating teams
    assert "sec_fresh" in teams_in_citrus
    assert "b10_fresh" in teams_in_citrus
    assert "sec_repeat" not in teams_in_citrus
    assert "b10_repeat" not in teams_in_citrus

def test_rematch_avoidance():
    from ballmonitor.models.ncaaf_bowls.domain import Game
    cfg = SimConfig(bowl_temperature=0.0)
    bowls = [
        Bowl(
            id="citrus_bowl",
            name="Cheez-It Citrus Bowl",
            city="Orlando", state="FL",
            lat=28.5, lon=-81.4,
            is_cfp=False,
            prestige=9, payout=8000000,
            slots=[{"confs": ["SEC"], "order": 1}, {"confs": ["Big Ten"], "order": 1}]
        )
    ]

    sec_team = Team("sec_1", "SEC Team", "SEC", 18.0, 980, 8, "City", "FL", 28.5, -81.4, 9, 3, 6, 2)
    b10_rematch = Team("b10_rematch", "B10 Rematch", "Big Ten", 19.0, 980, 9, "City", "OH", 40.0, -83.0, 9, 3, 6, 2)
    b10_fresh = Team("b10_fresh", "B10 Fresh", "Big Ten", 17.5, 980, 8, "City", "IN", 40.0, -86.0, 9, 3, 6, 2)

    # sec_team played b10_rematch in the regular season schedule
    regular_season_schedule = [Game(home="sec_1", away="b10_rematch", conf=False)]

    teams = [sec_team, b10_rematch, b10_fresh]
    states = {
        t.id: TeamSimState(team=t, wins=t.wins, losses=t.losses, conf_wins=t.conf_wins, conf_losses=t.conf_losses)
        for t in teams
    }

    selector = BowlSelector(bowls, teams, cfg, schedule=regular_season_schedule)
    rng = random.Random(42)
    matchups = selector.select_bowls(states, cfp_team_ids=set(), rng=rng)
    citrus = {m.bowl_id: m for m in matchups}["citrus_bowl"]
    teams_in_citrus = {citrus.team_1.id, citrus.team_2.id}

    # B10 fresh should be picked to avoid regular season rematch with sec_1
    assert "sec_1" in teams_in_citrus
    assert "b10_fresh" in teams_in_citrus
    assert "b10_rematch" not in teams_in_citrus


def test_legacy_pac12_school_fills_legacy_slot_not_its_conference():
    # 2026: a legacy Pac-12 school now in the Big Ten (e.g. USC) fills the Pac-12 legacy
    # slot, never a Big Ten slot; a new Pac-12 member fills the new-Pac-12 slot.
    cfg = SimConfig(bowl_temperature=0.0)
    bowls = [
        Bowl(id="las_vegas_bowl", name="Las Vegas Bowl", city="Paradise", state="NV", lat=36.1, lon=-115.2,
             is_cfp=False, prestige=7, slots=[{"confs": ["Big Ten"], "order": 1}, {"confs": ["Pac-12 legacy"], "order": 1}]),
        Bowl(id="poinsettia_bowl", name="Poinsettia Bowl", city="San Diego", state="CA", lat=32.8, lon=-117.1,
             is_cfp=False, prestige=5, slots=[{"confs": ["Pac-12"], "order": 1}, {"confs": ["Pac-12 legacy"], "order": 2}]),
    ]
    teams = [
        Team("usc", "USC", "Big Ten", 20.0, 980, 9, "LA", "CA", 34.0, -118.3, 9, 3, 6, 3, legacy_pac12=True),
        Team("ucla", "UCLA", "Big Ten", 12.0, 980, 7, "LA", "CA", 34.1, -118.4, 7, 5, 4, 5, legacy_pac12=True),
        Team("b10", "Big Ten Team", "Big Ten", 8.0, 980, 6, "X", "OH", 40.0, -83.0, 7, 5, 5, 4),
        Team("boise_state", "Boise State", "Pac-12", 15.0, 980, 6, "Boise", "ID", 43.6, -116.2, 10, 2, 7, 0),
    ]
    states = {t.id: TeamSimState(team=t, wins=t.wins, losses=t.losses, conf_wins=t.conf_wins,
                                 conf_losses=t.conf_losses) for t in teams}
    m = {x.bowl_id: x for x in BowlSelector(bowls, teams, cfg).select_bowls(states, set(), random.Random(1))}
    assert {m["las_vegas_bowl"].team_1.id, m["las_vegas_bowl"].team_2.id} == {"b10", "usc"}
    assert {m["poinsettia_bowl"].team_1.id, m["poinsettia_bowl"].team_2.id} == {"boise_state", "ucla"}
