import pytest
from ballmonitor.models.ncaaf_bowls.domain import Team
from ballmonitor.models.ncaaf_bowls.ratings import RatingManager

def test_load_builtin_ratings():
    teams = [
        Team("texas", "Texas", "SEC", 25.0, 980, 10, "", "", 0.0, 0.0, 7, 1, 3, 1),
        Team("alabama", "Alabama", "SEC", 22.0, 980, 10, "", "", 0.0, 0.0, 6, 2, 3, 2),
    ]

    # Default
    r_default = RatingManager.load_ratings("default", teams)
    assert r_default["texas"] == 25.0
    assert r_default["alabama"] == 22.0

    # Results-only fit
    r_res = RatingManager.load_ratings("results", teams)
    assert "texas" in r_res
    assert isinstance(r_res["texas"], float)

    # FPI
    r_fpi = RatingManager.load_ratings("fpi", teams)
    assert "alabama" in r_fpi

def test_custom_dict_and_blend():
    teams = [
        Team("t1", "Team 1", "SEC", 20.0, 980, 5, "", "", 0.0, 0.0, 6, 2, 3, 1),
        Team("t2", "Team 2", "SEC", 10.0, 980, 5, "", "", 0.0, 0.0, 5, 3, 2, 2),
    ]
    custom = {"t1": 25.0}
    r = RatingManager.load_ratings(custom, teams)
    assert r["t1"] == 25.0
    assert r["t2"] == 10.0  # falls back to team baseline

    # Blend
    blended = RatingManager.blend_ratings([({"t1": 20.0}, 1.0), ({"t1": 30.0}, 1.0)], teams)
    assert blended["t1"] == 25.0
