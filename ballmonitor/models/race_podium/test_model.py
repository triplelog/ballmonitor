"""Model-specific tests for race_podium."""

import math

import pytest

from ballmonitor.core import registry


@pytest.fixture
def model():
    return registry.load_model("race_podium")


def test_default_example(model):
    inputs = registry.load_example("race_podium", "default")
    pred = model.predict(inputs)

    assert len(pred.outcomes) >= 6
    # Verify positions 1 to 5 are strictly ordered (increasing time)
    top_5 = [o.estimate for o in pred.outcomes[:5]]
    assert top_5 == sorted(top_5)
    for i in range(len(top_5) - 1):
        assert top_5[i + 1] > top_5[i]

    # Verify probability outcome exists
    prob_outcome = pred.outcome("Aging-up runner wins division")
    assert prob_outcome.probability is not None
    assert 0.0 <= prob_outcome.probability <= 1.0


def test_ten_year_bracket(model):
    inputs = registry.load_example("race_podium", "ten_year_bracket")
    pred = model.predict(inputs)
    assert pred.primary.estimate is not None
    assert "F 40-49" in pred.inputs["Division"]


def test_field_size_scaling(model):
    base_inputs = {
        "race_name": "Test Race",
        "gender": "M",
        "age_min": 40,
        "age_max": 44,
        "history": [
            {"year": 2022, "field_size": 100, "times": ["55:00", "56:00", "57:00", "58:00", "59:00", "60:00"]},
            {"year": 2023, "field_size": 100, "times": ["55:00", "56:00", "57:00", "58:00", "59:00", "60:00"]},
        ],
    }

    # Small field (N=30)
    pred_small = model.predict({**base_inputs, "field_size": 30})
    # Large field (N=500)
    pred_large = model.predict({**base_inputs, "field_size": 500})

    # A larger field draws faster runners, so winning time must be faster (lower seconds)
    assert pred_large.primary.estimate < pred_small.primary.estimate

    # A larger field compresses the gap between 1st and 5th
    spread_small = pred_small.outcomes[4].estimate - pred_small.outcomes[0].estimate
    spread_large = pred_large.outcomes[4].estimate - pred_large.outcomes[0].estimate
    assert spread_large < spread_small


def test_aging_up_contender_impact(model):
    base_inputs = {
        "race_name": "Test Race",
        "gender": "M",
        "age_min": 40,
        "age_max": 44,
        "field_size": 100,
        "history": [
            {"year": 2023, "field_size": 100, "times": ["55:00", "55:45", "56:30", "57:15", "58:00", "58:45"]},
        ],
    }

    # Without aging-in contender
    pred_no_aging = model.predict(base_inputs)

    # With very fast 39-year-old aging into 40-44
    inputs_with_aging = {
        **base_inputs,
        "prior_runners": [{"name": "Fast Master", "age": 39, "time": "53:30", "gender": "M"}],
    }
    pred_with_aging = model.predict(inputs_with_aging)

    # Winning time should be faster with the aging contender
    assert pred_with_aging.primary.estimate < pred_no_aging.primary.estimate

    # Probability of aging-in win should be positive
    prob = pred_with_aging.outcome("Aging-up runner wins division").probability
    assert prob > 0.20


def test_weather_adjustment(model):
    base_inputs = {
        "race_name": "Autumn 10K",
        "distance": "10k",
        "gender": "M",
        "age_min": 0,
        "age_max": 99,
        "field_size": 200,
        "history": [
            {"year": 2023, "field_size": 200, "times": ["32:00", "32:40", "33:20", "34:00", "34:40", "35:20"]},
        ],
    }

    # Cool ideal day (50F, 40F dew point -> sum = 90 <= 100 -> 0% penalty)
    pred_cool = model.predict({**base_inputs, "forecast_temp_f": 50.0, "forecast_dew_point_f": 40.0})

    # Hot humid day (78F, 65F dew point -> sum = 143 > 100 -> heat penalty)
    pred_hot = model.predict({**base_inputs, "forecast_temp_f": 78.0, "forecast_dew_point_f": 65.0})

    # Hot day must be significantly slower than cool day
    assert pred_hot.primary.estimate > pred_cool.primary.estimate
    # Difference should be at least 30 seconds on a 10K
    assert (pred_hot.primary.estimate - pred_cool.primary.estimate) > 30.0


def test_overall_exclusion_displacement(model):
    base_inputs = {
        "race_name": "Spring 5K",
        "distance": "5k",
        "gender": "M",
        "age_min": 40,
        "age_max": 44,
        "field_size": 100,
        "history": [
            {"year": 2023, "field_size": 100, "times": ["16:00", "16:45", "17:15", "17:45", "18:15", "18:45"]},
        ],
    }

    # When overall winners are excluded (overall_awards_count = 3)
    pred_excluded = model.predict(base_inputs)

    # When overall exclusion is disabled (overall_awards_count = 0)
    pred_raw = model.predict({**base_inputs, "overall_awards_count": 0})

    # Excluding overall winners shifts age group awards slower (since top masters take overall medals)
    assert pred_excluded.primary.estimate >= pred_raw.primary.estimate


def test_backtest_case(model):
    row = {
        "race": "Cherry Blossom 10 Mile",
        "gender": "M",
        "age_min": "40",
        "age_max": "44",
        "field_size": "140",
        "hist_n_ref": "125",
        "hist_winning_mean": "54:20",
        "prior_fastest_aging_in": "53:40",
        "actual_time": "54:05",
    }
    inputs, actual = model.backtest_case(row)
    pred = model.predict(inputs)
    scores = model.score(pred, actual)

    assert "abs_error" in scores
    assert scores["abs_error"] < 60.0
    assert scores["in_interval"] == 1.0


def test_age_curve_dynamics():
    from ballmonitor.models.race_podium.age_curves import (
        continuous_age_factor,
        get_annual_aging_decline_pct,
        get_bracket_relative_factor,
        get_peak_endurance_age,
        predict_time_at_age_and_distance,
    )

    # 1. Peak age shifts with distance (5K peak younger than Marathon peak)
    peak_5k = get_peak_endurance_age(5000.0)
    peak_marathon = get_peak_endurance_age(42195.0)
    assert peak_marathon > peak_5k
    assert 22.0 <= peak_5k <= 25.0
    assert 30.0 <= peak_marathon <= 34.0

    # 2. Youth dynamics: 18yo has near-zero/negative penalty at 5k, but positive penalty at marathon
    f_18_5k = continuous_age_factor(18, 5000.0)
    f_18_marathon = continuous_age_factor(18, 42195.0)
    assert f_18_marathon > f_18_5k

    # 3. Masters endurance retention: 45yo slows down more at 5K than at Marathon relative to peak
    f_45_5k = continuous_age_factor(45, 5000.0)
    f_45_marathon = continuous_age_factor(45, 42195.0)
    # Slowdown relative to peak:
    assert (f_45_5k - 1.0) > (f_45_marathon - 1.0)

    # 4. Senior acceleration: decline rate per year accelerates after age 65
    slope_45 = get_annual_aging_decline_pct(45, 10000.0)
    slope_72 = get_annual_aging_decline_pct(72, 10000.0)
    assert slope_72 > slope_45 * 2.0  # Senior decline should be more than double masters decline

    # 5. Cross-distance & cross-age projection
    # 20:00 5k at age 25 converted to 10k at age 45
    proj_sec = predict_time_at_age_and_distance(
        time_sec=1200.0,
        from_age=25,
        from_dist_m=5000.0,
        to_age=45,
        to_dist_m=10000.0,
        gender="M",
    )
    # Riegel baseline for 10k is ~20:00 * 2^1.06 = ~41:48 (2508s), with age factor ~1.03 -> ~2580s (43 min)
    assert 2400.0 < proj_sec < 2800.0


def test_open_baseline_scaling(model):
    # Predict M 50-54 10K using open_baseline_time
    pred = model.predict({
        "race_name": "Midwest 10K",
        "distance": "10k",
        "gender": "M",
        "age_min": 50,
        "age_max": 54,
        "field_size": 80,
        "open_baseline_time": "32:00",
    })
    # Derived winning time should be roughly 32:00 * ~1.08 = ~34:30 (2070s)
    est = pred.primary.estimate
    assert est > 1920.0  # slower than 32:00
    assert est < 2250.0  # reasonable masters time (37:30)
    assert any("Derived division baseline from open baseline time" in s for s in pred.steps)


def test_smooth_division_field_size_adjacent_valley(model):
    # Test scenario: 30-34 division has an artificial dip of 4 runners,
    # but adjacent brackets are popular (25-29: 10, 35-39: 15) in a 90-person race.
    pred = model.predict({
        "race_name": "Small Town 5K",
        "distance": "5k",
        "gender": "F",
        "age_min": 30,
        "age_max": 34,
        "field_size": 4,
        "total_field_size": 90,
        "adjacent_counts": {
            "25-29": 10,
            "30-34": 4,
            "35-39": 15,
        },
        "history": [
            {"year": 2023, "field_size": 10, "times": ["22:00", "22:45", "23:30", "24:15", "25:00", "25:45"]},
        ],
    })

    # The expected field size should be smoothed from 4 up to ~9
    assert int(pred.inputs["Expected field size"]) >= 8
    assert any("Smoothed division field size from raw N=4" in s for s in pred.steps)


def test_field_size_estimation_from_total(model):
    # User provides only total_field_size = 500 for a 10K M 40-44
    pred = model.predict({
        "race_name": "Autumn 10K",
        "distance": "10k",
        "gender": "M",
        "age_min": 40,
        "age_max": 44,
        "total_field_size": 500,
        "history": [
            {"year": 2023, "field_size": 50, "times": ["36:00", "36:45", "37:30", "38:15", "39:00", "39:45"]},
        ],
    })

    # 10K M 40-44 demographic share is ~12.3% of men; men are 45% of 10K field -> expected division size is ~28
    assert 25 <= int(pred.inputs["Expected field size"]) <= 35
    assert any("Estimated division field size" in s for s in pred.steps)


def test_url_ingester_html_and_ascii():
    from bs4 import BeautifulSoup
    from ballmonitor.models.race_podium.ingest import RaceResultsIngester

    ingester = RaceResultsIngester()

    # 1. HTML table test
    html = """
    <table>
      <tr><th>Place</th><th>Name</th><th>Age</th><th>Sex</th><th>Time</th></tr>
      <tr><td>1</td><td>Mark Strong</td><td>42</td><td>M</td><td>17:40</td></tr>
      <tr><td>2</td><td>Elena Rostova</td><td>31</td><td>F</td><td>18:15</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    recs = ingester._parse_html_tables(soup)
    assert len(recs) == 2
    assert recs[0].first_name == "Mark"
    assert recs[0].age == 42
    assert recs[0].chip_time_sec == 1060.0

    # 2. ASCII monospace text test
    ascii_txt = """
    PLACE NAME            AGE S TIME
    ===== =============== === = =====
        1 Jack Reacher     45 M 16:50
        2 Sarah Connor     38 F 17:35
    """
    recs_ascii = ingester._parse_ascii_text(ascii_txt)
    assert len(recs_ascii) == 2
    assert recs_ascii[0].first_name == "Jack"
    assert recs_ascii[0].chip_time_sec == 1010.0


def test_discover_race_years_dropdown_and_links():
    from ballmonitor.models.race_podium.ingest import RaceResultsIngester

    ingester = RaceResultsIngester()

    # 1. Select dropdown with relative URLs
    html_select = """
    <html>
      <body>
        <select name="race_year" id="year-select">
          <option value="/results/2024" selected>2024 Results</option>
          <option value="/results/2023">2023 Results</option>
          <option value="/results/2022">2022 Results</option>
          <option value="/results/2021">2021 Results</option>
        </select>
      </body>
    </html>
    """
    discovered_select = ingester.discover_race_years("https://timing.com/results/2024", html=html_select)
    assert 2024 in discovered_select
    assert 2023 in discovered_select
    assert 2022 in discovered_select
    assert 2021 in discovered_select
    assert discovered_select[2023] == "https://timing.com/results/2023"

    # 2. Archive links (<a> tags)
    html_links = """
    <html>
      <body>
        <div class="archive-nav">
          <a href="/archive/2024">2024 Results</a>
          <a href="/archive/2023">2023</a>
          <a href="/archive/2022">2022</a>
        </div>
      </body>
    </html>
    """
    discovered_links = ingester.discover_race_years("https://timing.com/archive/2024", html=html_links)
    assert 2024 in discovered_links
    assert 2023 in discovered_links
    assert 2022 in discovered_links
    assert discovered_links[2023] == "https://timing.com/archive/2023"

    # 3. Form action with parameter dropdown
    html_form = """
    <html>
      <body>
        <form action="/view_results.php" method="GET">
          <select name="yr">
            <option value="2024">2024</option>
            <option value="2023">2023</option>
            <option value="2022">2022</option>
          </select>
        </form>
      </body>
    </html>
    """
    discovered_form = ingester.discover_race_years("https://timing.com/results", html=html_form)
    assert 2024 in discovered_form
    assert 2023 in discovered_form
    assert discovered_form[2023] == "https://timing.com/view_results.php?yr=2023"


def test_ingest_multi_year_mock():
    from ballmonitor.models.race_podium.ingest import RaceResultsIngester

    html_2024 = """
    <html>
      <head><title>Spring 5K 2024</title></head>
      <body>
        <select name="year">
          <option value="/race/2024">2024</option>
          <option value="/race/2023">2023</option>
        </select>
        <table>
          <tr><th>Place</th><th>Name</th><th>Age</th><th>Sex</th><th>Time</th></tr>
          <tr><td>1</td><td>Liam Davis</td><td>28</td><td>M</td><td>15:30</td></tr>
          <tr><td>2</td><td>Marcus Vance</td><td>40</td><td>M</td><td>16:45</td></tr>
        </table>
      </body>
    </html>
    """

    html_2023 = """
    <html>
      <head><title>Spring 5K 2023</title></head>
      <body>
        <table>
          <tr><th>Place</th><th>Name</th><th>Age</th><th>Sex</th><th>Time</th></tr>
          <tr><td>1</td><td>Liam Davis</td><td>27</td><td>M</td><td>15:40</td></tr>
          <tr><td>2</td><td>Marcus Vance</td><td>39</td><td>M</td><td>16:30</td></tr>
        </table>
      </body>
    </html>
    """

    ingester = RaceResultsIngester()
    html_by_url = {
        "https://races.com/race/2024": html_2024,
        "https://races.com/race/2023": html_2023,
    }

    editions = ingester.ingest_multi_year("https://races.com/race/2024", html_by_url=html_by_url)
    assert len(editions) == 2
    assert editions[0]["year"] == 2024
    assert editions[1]["year"] == 2023
    assert len(editions[0]["records"]) == 2
    assert len(editions[1]["records"]) == 2


def test_bracket_breakdowns_and_board(model):
    # Test all 3 common breakdowns
    for breakdown, expected_count in [("5-year", 30), ("10-year", 14), ("masters", 10)]:
        board = model.predict_all_brackets(
            {"race_name": "Test Run", "distance": "5k", "total_field_size": 400},
            breakdown=breakdown,
        )
        assert board["total_divisions"] == expected_count
        assert len(board["divisions"]) == expected_count
        assert "summary_table" in board
        assert "| Division | Exp. Field | 1st Place |" in board["summary_table"]

        # Ensure times are realistic
        div_0 = board["divisions"][0]
        assert div_0["winning_time_sec"] > 0
        assert len(div_0["podium_times"]) == 3


def test_model_predict_with_bracket_mode_and_multi_year_url(model):
    html_2024 = """
    <html>
      <head><title>Spring 10K 2024</title></head>
      <body>
        <select name="year">
          <option value="/10k/2024">2024</option>
          <option value="/10k/2023">2023</option>
        </select>
        <table>
          <tr><th>Place</th><th>Name</th><th>Age</th><th>Sex</th><th>Time</th></tr>
          <tr><td>1</td><td>Jack Hunter</td><td>26</td><td>M</td><td>31:10</td></tr>
          <tr><td>2</td><td>David Hall</td><td>40</td><td>M</td><td>33:45</td></tr>
          <tr><td>3</td><td>Brian Miller</td><td>39</td><td>M</td><td>33:15</td></tr>
          <tr><td>4</td><td>Sarah Connor</td><td>32</td><td>F</td><td>35:20</td></tr>
        </table>
      </body>
    </html>
    """

    html_2023 = """
    <html>
      <head><title>Spring 10K 2023</title></head>
      <body>
        <table>
          <tr><th>Place</th><th>Name</th><th>Age</th><th>Sex</th><th>Time</th></tr>
          <tr><td>1</td><td>Jack Hunter</td><td>25</td><td>M</td><td>31:25</td></tr>
          <tr><td>2</td><td>David Hall</td><td>39</td><td>M</td><td>33:30</td></tr>
          <tr><td>3</td><td>Sarah Connor</td><td>31</td><td>F</td><td>35:50</td></tr>
        </table>
      </body>
    </html>
    """

    html_by_url = {
        "https://races.com/10k/2024": html_2024,
        "https://races.com/10k/2023": html_2023,
    }

    pred = model.predict({
        "race_name": "Spring 10K",
        "distance": "10k",
        "gender": "M",
        "age_min": 40,
        "age_max": 44,
        "results_url": "https://races.com/10k/2024",
        "html_by_url": html_by_url,
        "bracket_mode": "masters",
    })

    # Discovered years should be present
    assert "Discovered years" in pred.inputs
    assert "2024" in pred.inputs["Discovered years"]
    assert "2023" in pred.inputs["Discovered years"]

    # Division board should be attached in extras
    assert "division_board" in pred.extras
    assert "division_table" in pred.extras
    board = pred.extras["division_board"]
    assert board["total_divisions"] == 10

    # Contender aging from 2023 (David Hall aged 39 turning 40) was tracked
    aging_outcome = pred.outcome("Aging-up runner wins division")
    assert aging_outcome is not None
    assert aging_outcome.probability > 0.0

    # Multi-division outcomes should be grouped
    awards_outcomes = [o for o in pred.outcomes if "Masters Awards" in (o.group or "")]
    assert len(awards_outcomes) == 10






def test_history_times_are_sorted(model):
    base = {"distance": "5k", "gender": "M", "age_min": 40, "age_max": 44, "field_size": 40}
    a = model.predict({**base, "history": [{"year": 2023, "field_size": 40, "times": ["18:00", "18:30", "19:00"]}]})
    b = model.predict({**base, "history": [{"year": 2023, "field_size": 40, "times": ["19:00", "18:00", "18:30"]}]})
    assert a.extras["final_times"] == b.extras["final_times"]


def test_field_size_defaults_to_historical_mean(model):
    pred = model.predict({
        "distance": "5k", "gender": "F", "age_min": 50, "age_max": 54,
        "history": [
            {"year": 2022, "field_size": 30, "times": ["21:00", "21:40", "22:10", "22:30", "22:50"]},
            {"year": 2023, "field_size": 50, "times": ["21:20", "21:50", "22:20", "22:40", "23:00"]},
        ],
    })
    # Expected field = recency-weighted mean of earlier fields (target year 2024)
    d = model.params.recency_decay
    expected = (30 * d + 50) / (d + 1)
    assert abs(pred.extras["n_target"] - expected) < 1e-9


def test_backtest_case_parses_history_column(model):
    row = {
        "race": "Test 5K", "gender": "F", "age_min": "0", "age_max": "99", "distance": "5k",
        "field_size": "40", "hist_winning_mean": "18:30",
        "history": "2022:35:18:20|18:40|19:00|19:10|19:30;2023:45:18:40|18:50|19:05|19:20|19:40",
        "prior_fastest_aging_in": "", "actual_time": "18:25",
    }
    inputs, actual = model.backtest_case(row)
    assert actual == 18 * 60 + 25
    assert [h["year"] for h in inputs["history"]] == [2022, 2023]
    assert inputs["history"][1]["field_size"] == 45
    pred = model.predict(inputs)
    assert pred.extras["n_target"] == 40.0
    assert pred.extras["target_year"] == 2024  # last edition + 1 when no year is given


@pytest.mark.parametrize("bad", [
    {"gender": "Q"},
    {"age_min": 50, "age_max": 40},
    {"field_size": 0},
    {"history": [{"year": 2023, "times": []}]},
    {"prior_runners": [{"name": "x", "time": "18:00"}]},
    {"history": None, "data_file": "no_such_file.csv"},
])
def test_bad_inputs_raise_value_error(model, bad):
    inputs = {
        "distance": "5k", "gender": "M", "age_min": 40, "age_max": 44, "field_size": 50,
        "history": [{"year": 2023, "field_size": 40, "times": ["18:00", "18:30", "19:00"]}],
        **bad,
    }
    if inputs.get("history") is None:
        inputs.pop("history")
    with pytest.raises(ValueError):
        model.predict(inputs)


def test_distance_classification_and_cleaning():
    from ballmonitor.models.race_podium.download_runsignup import clean_finishes, normalize_distance

    assert normalize_distance("15K", None) == "other"
    assert normalize_distance("1/2 Marathon", None) == "half"
    assert normalize_distance("Half Marathon", None) == "half"
    assert normalize_distance("VIRTUAL Half Marathon", None) == "other"
    assert normalize_distance("MTB 10 Mile", None) == "other"
    assert normalize_distance("5K Fun Run", None) == "5k"
    assert normalize_distance("10 Miler", None) == "10mi"

    def row(dist, ev, t, first="A", last="B"):
        return {"race_id": "1", "year": "2024", "distance_cat": dist, "event_name": ev,
                "first_name": first, "last_name": last, "chip_time_sec": str(t)}

    rows = [
        row("5k", "5K", 1500),
        row("5k", "5K", 1500),                     # exact duplicate
        row("half", "Half Marathon", 4500, "C"),   # same person/time under two distances
        row("10k", "10K", 4500, "C"),
        row("5k", "15K", 4000, "D"),               # mis-classified 15K
        row("half", "Half Marathon", 1700, "E"),   # implausibly fast
    ]
    cleaned = clean_finishes(rows)
    assert len(cleaned) == 1 and cleaned[0]["first_name"] == "A"


# ---------------------------------------------------------------- v0.8 estimator


def _one_edition(n=40, t="18:00", **extra):
    return {
        "distance": "5k", "gender": "M", "age_min": 45, "age_max": 49, "field_size": n,
        "overall_awards_count": 0,
        "history": [{"year": 2024, "field_size": n, "times": [t, "18:30", "19:00", "19:20", "19:40"]}],
        **extra,
    }


def test_known_value_single_edition(model):
    # Same field size, no prior, no contender, no exclusion: 1st = last winner exactly,
    # sigma = sqrt((sy^2 + sf^2 * 100 / N) * (1 + 1 / w)), w = N / (N + half_n)
    p = model.params
    pred = model.predict(_one_edition(n=40))
    assert abs(pred.primary.estimate - 1080.0) < 1e-6
    w = p.recency_decay * 40 / (40 + p.edition_weight_half_n)  # edition 2024, target 2025
    sig = math.sqrt((p.sigma_year_pct**2 + p.sigma_field_pct**2 * 100 / 40) * (1 + 1 / w))
    assert abs(pred.extras["sigmas_pct"][0] - sig) < 1e-9
    lo, hi = pred.primary.interval
    z = 1.2815515655446004
    assert abs(lo - 1080 * math.exp(-z * sig / 100)) < 1e-6
    assert abs(hi - 1080 * math.exp(z * sig / 100)) < 1e-6


def test_order_score_shift_direction(model):
    small = model.predict(_one_edition(n=40) | {"field_size": 10})
    big = model.predict(_one_edition(n=40) | {"field_size": 200})
    assert big.primary.estimate < 1080.0 < small.primary.estimate
    # a bigger field is also more certain
    assert big.extras["sigmas_pct"][0] < small.extras["sigmas_pct"][0]


def test_tiny_editions_get_little_weight(model):
    base = {"distance": "5k", "gender": "F", "age_min": 30, "age_max": 34, "field_size": 30,
            "overall_awards_count": 0, "target_year": 2025}
    hist = [
        {"year": 2023, "field_size": 30, "times": ["20:00", "20:30", "21:00", "21:30", "22:00"]},
        {"year": 2024, "field_size": 1, "times": ["45:00"]},  # a lone walker
    ]
    pred = model.predict({**base, "history": hist})
    plain_mean = (1200 + 2700) / 2
    assert pred.primary.estimate < plain_mean - 300


def test_prior_pulls_small_division_toward_open(model):
    base = _one_edition(n=3) | {"field_size": 3, "history": [
        {"year": 2024, "field_size": 3, "times": ["30:00", "31:00", "32:00"]}]}
    no_prior = model.predict(base)
    with_prior = model.predict(base | {
        "open_history": [{"year": 2024, "field_size": 200, "times": ["16:00"]}],
    })
    assert with_prior.primary.estimate < no_prior.primary.estimate
    assert with_prior.extras["prior_times"][0] is not None
    # more prior weight -> closer to the prior
    m2 = registry.load_model("race_podium", overrides={"prior_weight": 5.0})
    strong = m2.predict(base | {"open_history": [{"year": 2024, "field_size": 200, "times": ["16:00"]}]})
    assert strong.primary.estimate < with_prior.primary.estimate


def test_recency_decay_favours_recent_editions(model):
    inputs = {
        "distance": "5k", "gender": "M", "age_min": 0, "age_max": 99, "field_size": 100,
        "target_year": 2025,
        "history": [
            {"year": 2020, "field_size": 100, "times": ["17:00"]},
            {"year": 2024, "field_size": 100, "times": ["16:00"]},
        ],
    }
    flat = model.predict(inputs).primary.estimate
    m2 = registry.load_model("race_podium", overrides={"recency_decay": 0.5})
    assert m2.predict(inputs).primary.estimate < flat


def test_backtest_case_reads_open_history_and_blank_field(model):
    row = {
        "race": "Test 5K", "year": "2025", "gender": "F", "age_min": "40", "age_max": "44",
        "distance": "5k", "field_size": "",
        "history": "2023:8:21:00|21:30|22:00;2024:12:20:40|21:10|21:50|22:10|22:30",
        "open_history": "2023:150:18:00;2024:170:17:50",
        "prior_fastest_aging_in": "", "actual_time": "20:55",
    }
    inputs, actual = model.backtest_case(row)
    assert actual == 20 * 60 + 55
    assert inputs["overall_awards_count"] == 0 and "field_size" not in inputs
    assert [e["field_size"] for e in inputs["open_history"]] == [150, 170]
    pred = model.predict(inputs)
    d = model.params.recency_decay
    assert abs(pred.extras["n_target"] - (8 * d * d + 12 * d) / (d * d + d)) < 1e-9
    assert pred.extras["estimate_mode"] == "history"
    assert pred.primary.interval[0] < actual < pred.primary.interval[1]


def test_board_threshold_is_a_parameter():
    inputs = {"race_name": "T", "distance": "5k", "field_size": 120}
    m_low = registry.load_model("race_podium", overrides={"board_total_field_threshold": 100})
    m_high = registry.load_model("race_podium")
    low = m_low.predict_all_brackets(inputs, breakdown="masters")
    high = m_high.predict_all_brackets(inputs, breakdown="masters")
    # 120 > 100: read as the race total and split; 120 <= 150: used as each division's size
    assert high["divisions"][0]["field_size"] == 120
    assert low["divisions"][0]["field_size"] < 120


def test_site_page(model):
    from ballmonitor.core import views
    from ballmonitor.models.race_podium import site

    pg = site.page(model)
    assert views.check(pg) == []
    picker, index = pg["views"]
    assert len(picker["options"]) == len(index["rows"]) > 10
    for opt in picker["options"]:
        for row in opt["views"][0]["rows"]:
            assert row["t1"] > 0
            assert row["t2"] is None or row["t2"] >= row["t1"]
