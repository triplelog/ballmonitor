import pytest
from ballmonitor.models.ncaaf_bowls.config import SimConfig
from ballmonitor.models.ncaaf_bowls.engine import BowlEngine
from ballmonitor.models.ncaaf_bowls.scenarios import Scenario

def test_engine_runs_and_aggregates_with_opponents_and_win_odds():
    config = SimConfig(simulations=50, random_seed=42)
    engine = BowlEngine(config=config)
    results = engine.run()

    assert results.total_simulations == 50
    assert len(results.team_summaries) == len(engine.teams) == 138
    assert len(results.bowl_summaries) == 41

    texas = results.team_summaries["texas"]
    assert 0.0 <= texas.p_eligible <= 1.0
    assert 0.0 <= texas.p_cfp <= 1.0
    assert 0.0 <= texas.p_win_any_bowl <= 1.0
    assert 0.0 <= texas.p_play_postseason <= 1.0

    # Opponent tracking
    assert len(texas.overall_opponents) > 0
    opp, p_opp, wr = texas.overall_opponents[0]
    assert 0.0 <= p_opp <= 1.0
    assert 0.0 <= wr <= 1.0

    # Per-bowl opponent tracking & win odds
    for bid, detail in texas.bowls_detail.items():
        assert 0.0 <= detail.p_appear <= 1.0
        assert 0.0 <= detail.p_win_conditional <= 1.0
        assert 0.0 <= detail.p_win_unconditional <= 1.0
        for opp_name, cond_p, opp_wr in detail.opponents:
            assert 0.0 <= cond_p <= 1.0
            assert 0.0 <= opp_wr <= 1.0

def test_engine_with_win_out_scenario():
    """Winning out fixes a team's record: no losses beyond the ones already taken. Uses a team that
    still has games in the committed schedule (a fixed team, e.g. Michigan, goes stale once its
    season is over)."""
    config = SimConfig(simulations=30, random_seed=42)
    engine = BowlEngine(config=config)
    if not engine.schedule:
        pytest.skip("no games left in the committed schedule")
    team = engine.schedule[0].home
    base = engine.run().team_summaries[team]
    won_out = BowlEngine(config=config).run(scenario=Scenario(wins_out={team})).team_summaries[team]
    assert len(won_out.record_dist) == 1   # one possible record
    (wins, losses), = won_out.record_dist
    assert all(losses <= l for _, l in base.record_dist)   # never more losses than any simulation
    assert wins >= max(w for w, _ in base.record_dist)
    assert won_out.record_mean_wins == wins
    if wins >= 6:
        assert won_out.p_eligible == 1.0


def test_conference_pecking_order():
    config = SimConfig(simulations=50, random_seed=42)
    engine = BowlEngine(config=config)
    results = engine.run()

    assert "SEC" in results.conference_pecking_orders
    assert "Big 12" in results.conference_pecking_orders
    assert "Big Ten" in results.conference_pecking_orders

    sec_rows = results.conference_pecking_orders["SEC"]
    assert len(sec_rows) > 10
    row = sec_rows[0]
    assert "p_rank_1" in row
    assert "p_rank_2" in row
    assert 0.0 <= row["p_rank_1"] <= 1.0
