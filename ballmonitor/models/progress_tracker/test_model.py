import datetime as dt
import math

import pytest

from ballmonitor.core import registry

D0 = dt.date(2026, 1, 5)


def run(inputs, variant=None, **overrides):
    return registry.load_model("progress_tracker", variant, overrides).predict(inputs)


def day(weeks):
    return D0 + dt.timedelta(days=round(7 * weeks))


def plan(entries, metric="chess_rating", shape="even", goal=200.0, weeks=10, **extra):
    """Start = first entry (D0); goal after `weeks` weeks."""
    return {"metric": metric, "shape": shape, "goal_value": goal, "goal_date": day(weeks),
            "entries": [{"date": day(w), "value": v} for w, v in entries], **extra}


def test_plan_shapes_hand_checked():
    # start 100 -> goal 200 over 10 weeks; at week 5 (t = 0.5) with k = 2
    for shape, share in (("even", 0.5), ("faster_early", 1 - 0.5 ** 2), ("faster_late", 0.5 ** 2)):
        pred = run(plan([(0, 100)], shape=shape, today=day(5)), split_strength=2.0)
        assert pred.extras["planned_today"] == pytest.approx(100 + share * 100), shape


def test_log_scale_plan_is_geometric():
    pred = run(plan([(0, 100)], metric="lift", goal=400, today=day(5)))
    assert pred.extras["planned_today"] == pytest.approx(200.0)          # half-way in log space


def test_adherence_without_and_with_shrinkage():
    # even plan 100 -> 200 in 10 weeks; entries at weeks 2 and 4 made exactly half the planned progress
    entries = [(0, 100), (2, 110), (4, 120)]
    raw = run(plan(entries, today=day(4)), prior_weight=0.0)
    assert raw.extras["f"] == pytest.approx(0.5)
    assert raw.primary.estimate == pytest.approx(150.0)                  # start + f (goal - start)
    shrunk = run(plan(entries, today=day(4)), prior_weight=1.0)
    x = [20.0, 40.0]
    sxx = sum(v * v for v in x)
    sxy = sum(v * v / 2 for v in x)
    m = 50.0 ** 2                                                        # planned progress at half-time
    assert shrunk.extras["f"] == pytest.approx((sxy + m) / (sxx + m))
    assert 0.5 < shrunk.extras["f"] < 1


def test_ahead_and_behind_and_replan():
    entries = [(0, 100), (4, 150)]                                       # plan says 140 at week 4
    pred = run(plan(entries, today=day(4)), prior_weight=0.0)
    t = pred.extras["track"]
    assert t["planned"] == pytest.approx(140) and t["ahead"] and t["gap"] == pytest.approx(10)
    assert pred.outcome("Ahead (+) or behind (-) the plan").estimate == pytest.approx(10)
    # re-plan: 50 more points in 6 weeks
    assert pred.extras["replan"]["per_week"] == pytest.approx(50 / 6)
    behind = run(plan([(0, 100), (4, 120)], today=day(4)))
    assert not behind.extras["track"]["ahead"]
    assert behind.outcome("Ahead (+) or behind (-) the plan").estimate == pytest.approx(-20)
    # lower is better (goal below start): dropping faster than planned is ahead
    down = run(plan([(0, 90), (5, 84)], metric="body_weight", goal=80, today=day(5)))
    assert down.extras["track"]["ahead"] and down.outcome("Ahead (+) or behind (-) the plan").estimate > 0


def test_replan_keeps_the_shape():
    pred = run(plan([(0, 100), (2, 110)], shape="faster_early", today=day(2)), split_strength=2.0)
    row = next(r for r in pred.extras["weeks_table"] if r["date"] == day(6).isoformat())
    # from 110 at week 2 to 200 at week 10: at week 6, t = 0.5 of the remaining period
    assert row["replan"] == pytest.approx(110 + (1 - 0.5 ** 2) * 90)
    assert pred.extras["weeks_table"][-1]["date"] == day(10).isoformat()


def test_wrong_way_shows_the_latest_entry():
    pred = run(plan([(0, 100), (3, 95), (5, 90)], today=day(5)), prior_weight=0.0)
    assert pred.extras["f"] < 0 and pred.extras["wrong_way"]
    assert pred.primary.estimate == pytest.approx(90.0) and pred.primary.interval is None


def test_no_entries_since_start_means_on_plan():
    pred = run({"metric": "lift", "start_date": D0, "start_value": 100, "goal_value": 120, "goal_date": day(20),
                "entries": [], "today": day(1)})
    assert pred.extras["f"] == 1.0 and pred.primary.estimate == pytest.approx(120.0)


def test_adherence_is_capped():
    pred = run(plan([(0, 100), (1, 190)], today=day(1)), prior_weight=0.0)
    assert pred.extras["f"] == pytest.approx(3.0)


def test_recency_weighting_follows_recent_entries():
    entries = [(0, 100), (2, 100), (4, 100), (6, 160)]
    equal = run(plan(entries, today=day(6)), prior_weight=0.0).extras["f"]
    recent = run(plan(entries, today=day(6)), prior_weight=0.0, recency_half_life_weeks=1.0).extras["f"]
    assert recent > equal


def test_steeper_split_moves_plan_values():
    a = run(plan([(0, 100)], shape="faster_early", today=day(3))).extras["planned_today"]
    b = run(plan([(0, 100)], shape="faster_early", today=day(3)), "steep_split").extras["planned_today"]
    assert b > a


def test_refusals():
    with pytest.raises(ValueError, match="goal"):
        run({"metric": "lift", "entries": [{"date": D0, "value": 100}]})
    with pytest.raises(ValueError, match="goal date"):
        run(plan([(0, 100)], weeks=-1))
    with pytest.raises(ValueError, match="differ"):
        run(plan([(0, 100)], goal=100))
    with pytest.raises(ValueError, match="above 0"):
        run(plan([(0, 100), (1, 0)], metric="lift"))
    with pytest.raises(ValueError, match="shape"):
        run(plan([(0, 100)], shape="zigzag"))


def next_goal(entries, **kw):
    over = {k: kw.pop(k) for k in ("catch_up_share", "on_track_tolerance") if k in kw}
    last = max(w for w, _ in entries)
    return run(plan(entries, today=day(last), **kw), **over).extras["next_goal"]


def test_next_week_goal_on_plan_and_ahead():
    # even plan 100 -> 200 in 10 weeks: the plan says 140 at week 4 and 150 at week 5
    g = next_goal([(0, 100), (4, 140)])
    assert g["reason"] == "on_plan" and g["value"] == pytest.approx(150) and g["date"] == day(5).isoformat()
    g = next_goal([(0, 100), (4, 150)])                       # 10 ahead: keep your own pace, never go back to 150
    assert g["reason"] == "ahead" and g["value"] == pytest.approx(160)
    g = next_goal([(0, 100), (4, 139.5)])                     # within the tolerance (0.1 x a 10-point step)
    assert g["reason"] == "on_plan" and g["value"] == pytest.approx(150)


def test_next_week_goal_behind_and_clamps():
    g = next_goal([(0, 100), (4, 130)])                       # 130 + 10 + 0.25 x 10
    assert g["reason"] == "catch_up" and g["value"] == pytest.approx(142.5) and g["change"] == pytest.approx(12.5)
    g = next_goal([(0, 100), (4, 130)], catch_up_share=1.5)   # 155 would pass the waypoint 150
    assert g["reason"] == "waypoint" and g["value"] == pytest.approx(150)
    g = next_goal([(0, 100), (9, 150)])                       # a week left: 150 + 10 + 10 = 170 < the re-plan (200)
    assert g["reason"] == "minimum" and g["value"] == pytest.approx(200)


def test_next_week_goal_decreasing_measure():
    # body weight 90 -> 80 in 10 weeks: plan 86 at week 4, 85 at week 5; logged 87 (1 kg behind)
    g = next_goal([(0, 90), (4, 87)], metric="body_weight", goal=80)
    assert g["reason"] == "catch_up" and g["value"] == pytest.approx(87 - 1 - 0.25)
    g = next_goal([(0, 90), (4, 85)], metric="body_weight", goal=80)   # ahead: keep losing 1 kg a week
    assert g["reason"] == "ahead" and g["value"] == pytest.approx(84)


def test_next_week_goal_on_log_scale():
    # lift 100 -> 200 even over 10 weeks, in log space; logged 125 at week 4 (plan 100 x 2^0.4)
    g = next_goal([(0, 100), (4, 125)], metric="lift")
    gap = math.log(100 * 2 ** 0.4 / 125)
    assert g["reason"] == "catch_up"
    assert g["value"] == pytest.approx(125 * math.exp(0.1 * math.log(2) + 0.25 * gap))


def test_next_week_goal_reached_or_past():
    assert next_goal([(0, 100), (4, 210)])["reason"] == "reached"
    assert next_goal([(0, 100), (11, 150)])["reason"] == "past_goal_date"
    pred = run(plan([(0, 100), (4, 130)], today=day(4)))
    assert pred.outcomes[1].label.startswith("Next week's goal") and pred.outcomes[1].estimate == pytest.approx(142.5)


def test_next_week_goal_from_today_when_the_entry_is_stale():
    # even plan 100 -> 200 in 10 weeks; last entry 140 at week 4 (on plan then), today is week 6
    pred = run(plan([(0, 100), (4, 140)], today=day(6)))
    g = pred.extras["next_goal"]
    assert g["date"] == day(7).isoformat()
    # plan 160 at week 6: 20 behind; step 10 -> 140 + 10 + 0.25 x 20 = 155; re-plan from (week 6, 140): 140 + 60/4 = 155
    assert g["reason"] in ("catch_up", "minimum") and g["value"] == pytest.approx(155.0)
    # with a smaller catch-up share the re-plan minimum wins
    g = run(plan([(0, 100), (4, 140)], today=day(6)), catch_up_share=0.1).extras["next_goal"]
    assert g["reason"] == "minimum" and g["value"] == pytest.approx(155.0)
    # stale past the goal date
    assert run(plan([(0, 100), (4, 140)], today=day(10))).extras["next_goal"]["reason"] == "past_goal_date"
