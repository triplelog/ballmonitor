import math

import pytest

from ballmonitor.core import registry
from ballmonitor.models.baseball_birthplaces import engine as E


def load(**overrides):
    return registry.load_model("baseball_birthplaces", None, overrides)


def run(example="default", **overrides):
    return load(**overrides).predict(registry.load_example("baseball_birthplaces", example))


def test_projection_centre_and_distances():
    assert E.laea(33.0, -88.0, 33.0, -88.0) == pytest.approx((0.0, 0.0), abs=1e-9)
    # equal-area projection: distances near the centre are close to great-circle distances
    x, y = E.laea(40.71, -74.0, 39.0, -80.0)   # NYC from a centre in West Virginia
    great = 6371.0088 * math.acos(math.sin(math.radians(39)) * math.sin(math.radians(40.71))
                                  + math.cos(math.radians(39)) * math.cos(math.radians(40.71)) * math.cos(math.radians(6)))
    assert math.hypot(x, y) == pytest.approx(great, rel=0.002)


def test_overlap_hand_cases():
    assert E.overlap(5, 10, 0) == 1 and E.overlap(11, 10, 0) == 0
    assert E.overlap(0, 10, 2) == 1            # the birthplace disk is inside the circle
    assert E.overlap(0, 2, 10) == pytest.approx(0.04)   # circle inside the disk: (2/10)^2
    assert E.overlap(20, 10, 10) == 0
    assert E.overlap(10, 10, 0.05) == pytest.approx(0.5, abs=0.01)   # a tiny disk on the edge: about half
    assert E.overlap(10, 10, 1e-6) == 1                              # under 10 m: a point (on the line counts)
    # two equal circles half a radius apart: lens area / circle area
    r, d = 1.0, 1.0
    lens = 2 * r * r * math.acos(d / (2 * r)) - d / 2 * math.sqrt(4 * r * r - d * d)
    assert E.overlap(d, r, r) == pytest.approx(lens / (math.pi * r * r))


def test_png_round_trip():
    import numpy as np
    code = np.array([[0, 1, 300], [65535, 12000, 7]], dtype=np.uint16)
    assert E.read_png(E.png_bytes(code)) == code.tolist()


def test_ladder_and_disk():
    p = load().params
    lad = E.ladder(p)
    assert lad[0] == p.min_radius_km and lad[-1] == p.max_radius_km and lad == sorted(lad)
    k = E.disk_kernel(50.0, 10.0)
    assert k.sum() * 100 == pytest.approx(math.pi * 50 ** 2, rel=0.02)   # area of the disk in km²


def test_decades():
    p = load().params
    assert E.decade_for(1987, p) == 1980 and E.decade_for(1832, p) == 1840 and E.decade_for(None, p) is None


def test_default_example_san_pedro_1980s():
    pred = run()
    assert pred.extras["frame"] == "main"
    assert 20 < pred.extras["radius_km"] < 120           # a million people around San Pedro de Macorís
    assert pred.extras["players"] > 20                    # a famous hotbed
    assert pred.extras["value"] == pytest.approx(pred.extras["players"])   # value = players


def test_formulas_move_the_value():
    base = run()
    hr = run(**{"formulas.value": "HR"})
    assert hr.extras["value"] > base.extras["value"]
    fewer = run(**{"formulas.include": "G >= 500"})
    assert fewer.extras["players"] < base.extras["players"]
    nothing = run(**{"formulas.include": "0", "formulas.value": "HR / players"})
    assert nothing.extras["value"] is None               # 0/0: no value, not an error


def test_spread_dilutes_big_cities():
    pinned = run("home_runs_la_1950s", max_spread_km=0.0)
    spread = run("home_runs_la_1950s")
    assert spread.extras["players"] < pinned.extras["players"]   # LA births no longer all downtown


def test_exactly_per_million():
    pred = run()
    held = pred.extras["people_in_circle"]
    assert abs(held / 1_000_000 - 1) < 0.02           # the circle holds about a million...
    # ...and the count is scaled to exactly per million by the people actually in it
    assert pred.extras["players"] == pytest.approx(pred.extras["value"])


def test_other_decades_in_the_value_formula():
    base = run()
    ratio = run(**{"formulas.value": "players_1980 / players_1950"})
    fifties = run(**{"formulas.value": "players_1950"})
    assert ratio.extras["value"] == pytest.approx(base.extras["players"] / fifties.extras["value"])
    with pytest.raises(Exception):
        run(**{"formulas.value": "HR_1915"})        # not a decade
    assert any("1950s" in s for s in ratio.steps)


def test_grid_settings_need_a_rebuild():
    # the circles are prebuilt by fetch.py; a different `people` is reported, not silently ignored
    pred = run(people=500000)
    assert pred.extras["stale_grid"] and any("rebuild" in s for s in pred.steps)
    assert not run().extras["stale_grid"]


def test_point_in_polygon_and_disk_points():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert list(E.inside([5, 11, -1, 9.99], [5, 5, 5, 0.01], sq)) == [True, False, False, True]
    pts = E.disk_points(4.0)
    assert len(pts) == 19 and max(math.hypot(x, y) for x, y in pts) == pytest.approx(4 * 0.866)
    assert E.disk_points(0.0) == [(0.0, 0.0)]


def test_region_population_of_whole_cells():
    import numpy as np
    frame = {"x0": 0.0, "y0": 0.0, "nx": 3, "ny": 2, "cell": 20.0}
    pop = E.pop_encode(np.array([[1000.0, 0.0, 5.0], [200.0, 300.0, 0.0]]))
    # a box exactly around the bottom-left cell (column 0, row 1): its 200 people
    assert E.region_population(pop, frame, [(0, 0), (20, 0), (20, 20), (0, 20)]) == pytest.approx(200, rel=1e-3)
    # half of the top-left cell (by its sample points): 500 of its 1,000
    assert E.region_population(pop, frame, [(0, 20), (10, 20), (10, 40), (0, 40)]) == pytest.approx(500, rel=1e-3)


def test_region_example_dominican_republic():
    pred = run("region_dominican_republic")
    total = pred.extras["total"]
    assert 400 < total["players"] < 1000                  # several hundred big-leaguers born in the D.R.
    assert 5e6 < pred.extras["decades"][2000]["people"] < 1.3e7   # about 9 million people in 2005
    assert pred.extras["decades"][1920]["players"] < 5     # almost none before integration
    socal = run("region_southern_california", **{"formulas.value": "HR"})
    assert socal.extras["total"]["value"] > 0
