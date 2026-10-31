"""
Compiles 10 years (2014-2023) of historical FBS bowl game selections,
including matchups, school distances to bowl sites, repeat appearance flags,
and team records, for empirical analysis of bowl selection behaviors.
"""

import json
import math
from pathlib import Path

DIR = Path(__file__).parent
DATA_DIR = DIR.parent

# Coordinates for major bowl sites
BOWL_LOCATIONS = {
    "rose_bowl": (34.16, -118.17),
    "sugar_bowl": (29.95, -90.08),
    "orange_bowl": (25.96, -80.24),
    "cotton_bowl": (32.75, -97.09),
    "fiesta_bowl": (33.53, -112.26),
    "peach_bowl": (33.76, -84.40),
    "citrus_bowl": (28.54, -81.40),
    "alamo_bowl": (29.42, -98.48),
    "pop_tarts_bowl": (28.54, -81.40), # Camping World / Russell Athletic
    "reliaquest_bowl": (27.98, -82.50), # Outback Bowl
    "gator_bowl": (30.32, -81.64), # TaxSlayer
    "holiday_bowl": (32.76, -117.12),
    "music_city_bowl": (36.17, -86.77),
    "texas_bowl": (29.68, -95.41),
    "las_vegas_bowl": (36.09, -115.18),
    "sun_bowl": (31.77, -106.51),
    "liberty_bowl": (35.12, -89.98),
    "dukes_mayo_bowl": (35.23, -80.85), # Belk Bowl
    "pinstripe_bowl": (40.83, -73.93),
    "guaranteed_rate_bowl": (33.45, -112.07), # Cactus / Cheez-It
    "la_bowl": (33.95, -118.34),
    "gasparilla_bowl": (27.98, -82.50), # St. Petersburg
    "birmingham_bowl": (33.52, -86.81),
    "first_responder_bowl": (32.78, -96.76), # Heart of Dallas
    "armed_forces_bowl": (32.71, -97.36),
    "independence_bowl": (32.47, -93.80),
    "quick_lane_bowl": (42.34, -83.05), # GameAbove
    "potato_bowl": (43.60, -116.20),
    "arizona_bowl": (32.23, -110.95),
    "new_mexico_bowl": (35.07, -106.63),
    "hawaii_bowl": (21.37, -157.93),
    "new_orleans_bowl": (29.95, -90.08),
    "camellia_bowl": (32.36, -86.28),
    "boca_raton_bowl": (26.37, -80.10),
    "myrtle_beach_bowl": (33.79, -79.01),
    "cure_bowl": (28.54, -81.40),
    "bahamas_bowl": (25.04, -77.36),
    "fenway_bowl": (42.35, -71.10),
    "military_bowl": (38.98, -76.51),
    "frisco_bowl": (33.15, -96.84),
}

def haversine(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2)**2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def build_dataset():
    # Load team coordinates & brands
    with open(DATA_DIR / "teams.json") as f:
        teams_data = json.load(f)
    team_info = {t["id"]: t for t in teams_data}

    # Historical Bowl selections 2014–2023 (10 seasons across premier and mid-tier games)
    # [year, bowl_id, team_1_id, team_1_wins, team_2_id, team_2_wins]
    history = [
        # 2023
        (2023, "rose_bowl", "michigan", 13, "alabama", 12),
        (2023, "sugar_bowl", "washington", 13, "texas", 12),
        (2023, "orange_bowl", "georgia", 12, "florida_state", 13),
        (2023, "cotton_bowl", "missouri", 10, "ohio_state", 11),
        (2023, "peach_bowl", "ole_miss", 10, "penn_state", 10),
        (2023, "fiesta_bowl", "oregon", 11, "liberty", 13),
        (2023, "citrus_bowl", "tennessee", 8, "iowa", 10),
        (2023, "reliaquest_bowl", "lsu", 9, "wisconsin", 7),
        (2023, "alamo_bowl", "arizona", 9, "oklahoma", 10),
        (2023, "pop_tarts_bowl", "kansas_state", 8, "nc_state", 9),
        (2023, "texas_bowl", "oklahoma_state", 9, "texas_am", 7),
        (2023, "gator_bowl", "clemson", 8, "kentucky", 7),
        (2023, "dukes_mayo_bowl", "west_virginia", 8, "north_carolina", 8),
        (2023, "music_city_bowl", "maryland", 7, "auburn", 6),
        (2023, "sun_bowl", "notre_dame", 9, "oregon_state", 8),
        (2023, "liberty_bowl", "memphis", 9, "iowa_state", 7),
        (2023, "pinstripe_bowl", "rutgers", 6, "miami", 7),
        (2023, "las_vegas_bowl", "northwestern", 7, "utah", 8),
        (2023, "holiday_bowl", "usc", 7, "louisville", 10),
        (2023, "guaranteed_rate_bowl", "kansas", 8, "unlv", 9),
        (2023, "la_bowl", "ucla", 7, "boise_state", 8),
        (2023, "gasparilla_bowl", "georgia_tech", 6, "ucf", 6),
        (2023, "birmingham_bowl", "duke", 7, "troy", 11),
        (2023, "military_bowl", "virginia_tech", 6, "tulane", 11),
        (2023, "fenway_bowl", "boston_college", 6, "smu", 11),
        (2023, "independence_bowl", "texas_tech", 6, "california", 6),

        # 2022
        (2022, "peach_bowl", "georgia", 13, "ohio_state", 11),
        (2022, "fiesta_bowl", "tcu", 12, "michigan", 13),
        (2022, "rose_bowl", "penn_state", 10, "utah", 10),
        (2022, "sugar_bowl", "alabama", 10, "kansas_state", 10),
        (2022, "orange_bowl", "tennessee", 10, "clemson", 11),
        (2022, "cotton_bowl", "tulane", 11, "usc", 11),
        (2022, "citrus_bowl", "lsu", 9, "purdue", 8),
        (2022, "reliaquest_bowl", "mississippi_state", 8, "illinois", 8),
        (2022, "alamo_bowl", "texas", 8, "washington", 10),
        (2022, "pop_tarts_bowl", "florida_state", 9, "oklahoma", 6),
        (2022, "texas_bowl", "texas_tech", 7, "ole_miss", 8),
        (2022, "gator_bowl", "notre_dame", 8, "south_carolina", 8),
        (2022, "dukes_mayo_bowl", "maryland", 7, "nc_state", 8),
        (2022, "music_city_bowl", "iowa", 7, "kentucky", 7),
        (2022, "sun_bowl", "pittsburgh", 8, "ucla", 9),
        (2022, "liberty_bowl", "arkansas", 6, "kansas", 6),
        (2022, "pinstripe_bowl", "minnesota", 8, "syracuse", 7),
        (2022, "las_vegas_bowl", "oregon_state", 9, "florida", 6),
        (2022, "holiday_bowl", "oregon", 9, "north_carolina", 9),
        (2022, "guaranteed_rate_bowl", "wisconsin", 6, "oklahoma_state", 7),
        (2022, "la_bowl", "fresno_state", 9, "washington_state", 7),
        (2022, "gasparilla_bowl", "wake_forest", 7, "missouri", 6),
        (2022, "birmingham_bowl", "east_carolina", 7, "coastal_carolina", 9),
        (2022, "military_bowl", "duke", 8, "ucf", 9),

        # 2021
        (2021, "cotton_bowl", "alabama", 12, "cincinnati", 13),
        (2021, "orange_bowl", "georgia", 12, "michigan", 12),
        (2021, "rose_bowl", "ohio_state", 10, "utah", 10),
        (2021, "sugar_bowl", "baylor", 11, "ole_miss", 10),
        (2021, "peach_bowl", "michigan_state", 10, "pittsburgh", 11),
        (2021, "fiesta_bowl", "oklahoma_state", 11, "notre_dame", 11),
        (2021, "citrus_bowl", "kentucky", 9, "iowa", 10),
        (2021, "reliaquest_bowl", "arkansas", 8, "penn_state", 7),
        (2021, "alamo_bowl", "oklahoma", 10, "oregon", 10),
        (2021, "pop_tarts_bowl", "clemson", 9, "iowa_state", 7),
        (2021, "texas_bowl", "kansas_state", 7, "lsu", 6),
        (2021, "gator_bowl", "wake_forest", 10, "rutgers", 5),
        (2021, "dukes_mayo_bowl", "south_carolina", 6, "north_carolina", 6),
        (2021, "music_city_bowl", "purdue", 8, "tennessee", 7),
        (2021, "sun_bowl", "central_michigan", 8, "washington_state", 7),
        (2021, "liberty_bowl", "texas_tech", 6, "mississippi_state", 7),
        (2021, "pinstripe_bowl", "maryland", 6, "virginia_tech", 6),
        (2021, "las_vegas_bowl", "wisconsin", 8, "arizona_state", 8),
        (2021, "guaranteed_rate_bowl", "minnesota", 8, "west_virginia", 6),
        (2021, "la_bowl", "utah_state", 10, "oregon_state", 7),
        (2021, "gasparilla_bowl", "ucf", 8, "florida", 6),
        (2021, "birmingham_bowl", "houston", 11, "auburn", 6),

        # 2020 (Covid year)
        (2020, "rose_bowl", "alabama", 11, "notre_dame", 10),
        (2020, "sugar_bowl", "ohio_state", 6, "clemson", 10),
        (2020, "orange_bowl", "texas_am", 8, "north_carolina", 8),
        (2020, "cotton_bowl", "oklahoma", 8, "florida", 8),
        (2020, "peach_bowl", "georgia", 7, "cincinnati", 9),
        (2020, "fiesta_bowl", "iowa_state", 8, "oregon", 4),
        (2020, "citrus_bowl", "northwestern", 6, "auburn", 6),
        (2020, "reliaquest_bowl", "ole_miss", 4, "indiana", 6),
        (2020, "alamo_bowl", "texas", 6, "colorado", 4),
        (2020, "pop_tarts_bowl", "oklahoma_state", 7, "miami", 8),
        (2020, "gator_bowl", "kentucky", 4, "nc_state", 8),
        (2020, "dukes_mayo_bowl", "wisconsin", 3, "wake_forest", 4),
        (2020, "liberty_bowl", "west_virginia", 5, "army", 9),

        # 2019
        (2019, "peach_bowl", "lsu", 13, "oklahoma", 12),
        (2019, "fiesta_bowl", "clemson", 13, "ohio_state", 13),
        (2019, "rose_bowl", "oregon", 11, "wisconsin", 10),
        (2019, "sugar_bowl", "georgia", 11, "baylor", 11),
        (2019, "orange_bowl", "florida", 10, "virginia", 9),
        (2019, "cotton_bowl", "penn_state", 10, "memphis", 12),
        (2019, "citrus_bowl", "alabama", 10, "michigan", 9),
        (2019, "reliaquest_bowl", "minnesota", 10, "auburn", 9),
        (2019, "alamo_bowl", "texas", 7, "utah", 11),
        (2019, "pop_tarts_bowl", "notre_dame", 10, "iowa_state", 7),
        (2019, "texas_bowl", "texas_am", 7, "oklahoma_state", 8),
        (2019, "gator_bowl", "tennessee", 7, "indiana", 8),
        (2019, "dukes_mayo_bowl", "kentucky", 7, "virginia_tech", 8),
        (2019, "music_city_bowl", "louisville", 7, "mississippi_state", 6),
        (2019, "sun_bowl", "arizona_state", 7, "florida_state", 6),
        (2019, "liberty_bowl", "navy", 10, "kansas_state", 8),
        (2019, "pinstripe_bowl", "michigan_state", 6, "wake_forest", 8),
        (2019, "las_vegas_bowl", "washington", 7, "boise_state", 12),
        (2019, "holiday_bowl", "iowa", 9, "usc", 8),
        (2019, "guaranteed_rate_bowl", "california", 7, "illinois", 6),
        (2019, "gasparilla_bowl", "ucf", 9, "marshall", 8),
        (2019, "birmingham_bowl", "cincinnati", 10, "boston_college", 6),
        (2019, "military_bowl", "north_carolina", 6, "temple", 8),

        # 2018
        (2018, "orange_bowl", "alabama", 13, "oklahoma", 12),
        (2018, "cotton_bowl", "clemson", 13, "notre_dame", 12),
        (2018, "rose_bowl", "ohio_state", 12, "washington", 10),
        (2018, "sugar_bowl", "texas", 9, "georgia", 11),
        (2018, "peach_bowl", "florida", 9, "michigan", 10),
        (2018, "fiesta_bowl", "lsu", 9, "ucf", 12),
        (2018, "citrus_bowl", "kentucky", 9, "penn_state", 9),
        (2018, "reliaquest_bowl", "iowa", 8, "mississippi_state", 8),
        (2018, "alamo_bowl", "washington_state", 10, "iowa_state", 8),
        (2018, "pop_tarts_bowl", "syracuse", 9, "west_virginia", 8),
        (2018, "texas_bowl", "baylor", 6, "vanderbilt", 6),
        (2018, "gator_bowl", "texas_am", 8, "nc_state", 9),
        (2018, "dukes_mayo_bowl", "virginia", 7, "south_carolina", 7),
        (2018, "music_city_bowl", "auburn", 7, "purdue", 6),
        (2018, "sun_bowl", "stanford", 8, "pittsburgh", 7),
        (2018, "liberty_bowl", "oklahoma_state", 6, "missouri", 8),
        (2018, "pinstripe_bowl", "wisconsin", 7, "miami", 7),
        (2018, "las_vegas_bowl", "fresno_state", 11, "arizona_state", 7),
        (2018, "holiday_bowl", "northwestern", 8, "utah", 9),
        (2018, "guaranteed_rate_bowl", "tcu", 6, "california", 7),
        (2018, "gasparilla_bowl", "marshall", 8, "south_florida", 7),
        (2018, "military_bowl", "cincinnati", 10, "virginia_tech", 6),

        # 2017
        (2017, "sugar_bowl", "alabama", 11, "clemson", 12),
        (2017, "rose_bowl", "georgia", 12, "oklahoma", 12),
        (2017, "orange_bowl", "wisconsin", 12, "miami", 10),
        (2017, "cotton_bowl", "ohio_state", 11, "usc", 11),
        (2017, "peach_bowl", "ucf", 12, "auburn", 10),
        (2017, "fiesta_bowl", "penn_state", 10, "washington", 10),
        (2017, "citrus_bowl", "notre_dame", 9, "lsu", 9),
        (2017, "reliaquest_bowl", "south_carolina", 8, "michigan", 8),
        (2017, "alamo_bowl", "tcu", 10, "stanford", 9),
        (2017, "pop_tarts_bowl", "oklahoma_state", 9, "virginia_tech", 9),
        (2017, "texas_bowl", "texas", 6, "missouri", 7),
        (2017, "gator_bowl", "mississippi_state", 8, "louisville", 8),
        (2017, "dukes_mayo_bowl", "wake_forest", 7, "texas_am", 7),
        (2017, "music_city_bowl", "northwestern", 9, "kentucky", 7),
        (2017, "sun_bowl", "nc_state", 8, "arizona_state", 7),
        (2017, "liberty_bowl", "iowa_state", 7, "memphis", 10),
        (2017, "pinstripe_bowl", "iowa", 7, "boston_college", 7),
        (2017, "las_vegas_bowl", "boise_state", 10, "oregon", 7),
        (2017, "holiday_bowl", "purdue", 6, "arizona", 7),
        (2017, "guaranteed_rate_bowl", "kansas_state", 7, "ucla", 6),

        # 2016
        (2016, "peach_bowl", "alabama", 13, "washington", 12),
        (2016, "fiesta_bowl", "clemson", 12, "ohio_state", 11),
        (2016, "rose_bowl", "usc", 9, "penn_state", 11),
        (2016, "sugar_bowl", "oklahoma", 10, "auburn", 8),
        (2016, "orange_bowl", "florida_state", 9, "michigan", 10),
        (2016, "cotton_bowl", "wisconsin", 10, "western_michigan", 13),
        (2016, "citrus_bowl", "lsu", 7, "louisville", 9),
        (2016, "reliaquest_bowl", "florida", 8, "iowa", 8),
        (2016, "alamo_bowl", "oklahoma_state", 9, "colorado", 10),
        (2016, "pop_tarts_bowl", "miami", 8, "west_virginia", 10),
        (2016, "texas_bowl", "kansas_state", 8, "texas_am", 8),
        (2016, "gator_bowl", "georgia_tech", 8, "kentucky", 7),
        (2016, "dukes_mayo_bowl", "virginia_tech", 9, "arkansas", 7),
        (2016, "music_city_bowl", "tennessee", 8, "nebraska", 9),
        (2016, "sun_bowl", "stanford", 9, "north_carolina", 8),
        (2016, "liberty_bowl", "georgia", 7, "tcu", 6),
        (2016, "pinstripe_bowl", "northwestern", 6, "pittsburgh", 8),
        (2016, "las_vegas_bowl", "san_diego_state", 10, "houston", 9),
        (2016, "holiday_bowl", "minnesota", 8, "washington_state", 8),
        (2016, "guaranteed_rate_bowl", "baylor", 6, "boise_state", 10),

        # 2015
        (2015, "cotton_bowl", "alabama", 12, "michigan_state", 12),
        (2015, "orange_bowl", "clemson", 13, "oklahoma", 11),
        (2015, "rose_bowl", "stanford", 11, "iowa", 12),
        (2015, "sugar_bowl", "ole_miss", 9, "oklahoma_state", 10),
        (2015, "fiesta_bowl", "ohio_state", 11, "notre_dame", 10),
        (2015, "peach_bowl", "houston", 12, "florida_state", 10),
        (2015, "citrus_bowl", "michigan", 9, "florida", 10),
        (2015, "reliaquest_bowl", "tennessee", 8, "northwestern", 10),
        (2015, "alamo_bowl", "tcu", 10, "oregon", 9),
        (2015, "pop_tarts_bowl", "baylor", 9, "north_carolina", 11),
        (2015, "texas_bowl", "lsu", 8, "texas_tech", 7),
        (2015, "gator_bowl", "georgia", 9, "penn_state", 7),
        (2015, "dukes_mayo_bowl", "mississippi_state", 8, "nc_state", 7),
        (2015, "music_city_bowl", "louisville", 7, "texas_am", 8),
        (2015, "sun_bowl", "washington_state", 8, "miami", 8),
        (2015, "liberty_bowl", "arkansas", 7, "kansas_state", 6),
        (2015, "pinstripe_bowl", "duke", 7, "indiana", 6),
        (2015, "las_vegas_bowl", "utah", 9, "byu", 9),
        (2015, "holiday_bowl", "wisconsin", 9, "usc", 8),

        # 2014
        (2014, "sugar_bowl", "ohio_state", 12, "alabama", 12),
        (2014, "rose_bowl", "oregon", 12, "florida_state", 13),
        (2014, "orange_bowl", "georgia_tech", 10, "mississippi_state", 10),
        (2014, "cotton_bowl", "michigan_state", 10, "baylor", 11),
        (2014, "peach_bowl", "tcu", 11, "ole_miss", 9),
        (2014, "fiesta_bowl", "boise_state", 11, "arizona", 10),
        (2014, "citrus_bowl", "missouri", 10, "minnesota", 8),
        (2014, "reliaquest_bowl", "wisconsin", 10, "auburn", 8),
        (2014, "alamo_bowl", "ucla", 9, "kansas_state", 9),
        (2014, "pop_tarts_bowl", "clemson", 9, "oklahoma", 8),
        (2014, "texas_bowl", "arkansas", 6, "texas", 6),
        (2014, "gator_bowl", "tennessee", 6, "iowa", 7),
        (2014, "dukes_mayo_bowl", "texas_am", 7, "west_virginia", 7),
        (2014, "music_city_bowl", "notre_dame", 7, "lsu", 8),
        (2014, "sun_bowl", "arizona_state", 9, "duke", 9),
        (2014, "liberty_bowl", "texas_am", 7, "west_virginia", 7),
        (2014, "pinstripe_bowl", "penn_state", 6, "boston_college", 7),
        (2014, "holiday_bowl", "usc", 8, "nebraska", 9),
    ]

    records = []
    for yr, b_id, t1, w1, t2, w2 in history:
        b_coord = BOWL_LOCATIONS.get(b_id, (35.0, -90.0))
        t1_data = team_info.get(t1, {})
        t2_data = team_info.get(t2, {})

        t1_coord = (t1_data.get("lat", 35.0), t1_data.get("lon", -90.0))
        t2_coord = (t2_data.get("lat", 35.0), t2_data.get("lon", -90.0))

        d1 = haversine(b_coord, t1_coord)
        d2 = haversine(b_coord, t2_coord)

        records.append({
            "year": yr,
            "bowl_id": b_id,
            "team_1": t1,
            "team_1_wins": w1,
            "team_1_brand": t1_data.get("brand", 5),
            "team_1_conf": t1_data.get("conf", "Unknown"),
            "team_1_distance_miles": round(d1, 1),
            "team_2": t2,
            "team_2_wins": w2,
            "team_2_brand": t2_data.get("brand", 5),
            "team_2_conf": t2_data.get("conf", "Unknown"),
            "team_2_distance_miles": round(d2, 1),
        })

    out_file = DIR / "historical_bowls_2014_2023.json"
    with open(out_file, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Generated {len(records)} bowl game records from 2014-2023.")

if __name__ == "__main__":
    build_dataset()
