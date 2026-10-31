import pytest
from ballmonitor.models.ncaaf_bowls.scenarios import Scenario

def test_scenario_parsing():
    sc = Scenario.from_string("texas:win_out,alabama:lose_out,michigan>ohio_state")
    assert "texas" in sc.wins_out
    assert "alabama" in sc.loses_out
    assert sc.is_forced("michigan", "ohio_state") == "michigan"
    assert sc.is_forced("ohio_state", "michigan") == "michigan"

def test_scenario_game_overrides():
    sc = Scenario(wins_out={"texas"}, loses_out={"oklahoma"})

    # Texas vs someone else -> Texas wins
    assert sc.is_forced("texas", "arkansas") == "texas"
    assert sc.is_forced("arkansas", "texas") == "texas"

    # Oklahoma vs someone else -> Oklahoma loses
    assert sc.is_forced("oklahoma", "missouri") == "missouri"
    assert sc.is_forced("missouri", "oklahoma") == "missouri"

    # Neutral game -> None
    assert sc.is_forced("georgia", "tennessee") is None
