import pytest
from ballmonitor.models.ncaaf_bowls.backtest import Backtester

def test_backtest_2023():
    bt = Backtester(season=2023)
    card = bt.run_backtest(sims=50)

    assert card.season == 2023
    assert card.teams_evaluated > 20
    assert 0.0 <= card.top_1_accuracy <= 1.0
    assert 0.0 <= card.top_3_accuracy <= 1.0
    assert 0.0 <= card.top_5_accuracy <= 1.0
    assert card.brier_score > 0.0
    assert len(card.summary_table()) > 100
