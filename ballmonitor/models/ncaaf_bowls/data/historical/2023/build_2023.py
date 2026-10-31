"""
Generates the 2023 college football backtest dataset:
- Snapshot of records and ratings at Week 11 of the 2023 season.
- Remaining games (Week 12-13 + Conference Championship Games).
- Ground truth actual bowl assignments for evaluating model accuracy.
"""

import json
from pathlib import Path

DIR = Path(__file__).parent

def build_2023():
    # 2023 Week 11 snapshot: records, power ratings
    teams = [
        {"id": "michigan", "name": "Michigan", "conf": "Big Ten", "rating": 26.0, "apr": 993, "brand": 10, "city": "Ann Arbor", "state": "MI", "lat": 42.27, "lon": -83.74, "wins": 10, "losses": 0, "conf_wins": 7, "conf_losses": 0},
        {"id": "ohio_state", "name": "Ohio State", "conf": "Big Ten", "rating": 25.0, "apr": 991, "brand": 10, "city": "Columbus", "state": "OH", "lat": 40.00, "lon": -83.02, "wins": 10, "losses": 0, "conf_wins": 7, "conf_losses": 0},
        {"id": "georgia", "name": "Georgia", "conf": "SEC", "rating": 26.5, "apr": 980, "brand": 10, "city": "Athens", "state": "GA", "lat": 33.95, "lon": -83.37, "wins": 10, "losses": 0, "conf_wins": 7, "conf_losses": 0},
        {"id": "alabama", "name": "Alabama", "conf": "SEC", "rating": 23.5, "apr": 990, "brand": 10, "city": "Tuscaloosa", "state": "AL", "lat": 33.21, "lon": -87.54, "wins": 9, "losses": 1, "conf_wins": 7, "conf_losses": 0},
        {"id": "washington", "name": "Washington", "conf": "Pac-12", "rating": 19.5, "apr": 980, "brand": 8, "city": "Seattle", "state": "WA", "lat": 47.65, "lon": -122.30, "wins": 10, "losses": 0, "conf_wins": 7, "conf_losses": 0, "legacy_pac12": True},
        {"id": "oregon", "name": "Oregon", "conf": "Pac-12", "rating": 23.0, "apr": 983, "brand": 9, "city": "Eugene", "state": "OR", "lat": 44.05, "lon": -123.07, "wins": 9, "losses": 1, "conf_wins": 6, "conf_losses": 1, "legacy_pac12": True},
        {"id": "texas", "name": "Texas", "conf": "Big 12", "rating": 21.5, "apr": 985, "brand": 10, "city": "Austin", "state": "TX", "lat": 30.28, "lon": -97.73, "wins": 9, "losses": 1, "conf_wins": 6, "conf_losses": 1},
        {"id": "florida_state", "name": "Florida State", "conf": "ACC", "rating": 18.0, "apr": 978, "brand": 9, "city": "Tallahassee", "state": "FL", "lat": 30.44, "lon": -84.30, "wins": 10, "losses": 0, "conf_wins": 8, "conf_losses": 0},
        {"id": "penn_state", "name": "Penn State", "conf": "Big Ten", "rating": 19.0, "apr": 989, "brand": 9, "city": "University Park", "state": "PA", "lat": 40.80, "lon": -77.86, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 2},
        {"id": "missouri", "name": "Missouri", "conf": "SEC", "rating": 15.0, "apr": 982, "brand": 7, "city": "Columbia", "state": "MO", "lat": 38.94, "lon": -92.33, "wins": 8, "losses": 2, "conf_wins": 4, "conf_losses": 2},
        {"id": "ole_miss", "name": "Ole Miss", "conf": "SEC", "rating": 15.5, "apr": 975, "brand": 8, "city": "Oxford", "state": "MS", "lat": 34.36, "lon": -89.53, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 2},
        {"id": "lsu", "name": "LSU", "conf": "SEC", "rating": 17.5, "apr": 974, "brand": 9, "city": "Baton Rouge", "state": "LA", "lat": 30.41, "lon": -91.18, "wins": 7, "losses": 3, "conf_wins": 5, "conf_losses": 2},
        {"id": "oklahoma", "name": "Oklahoma", "conf": "Big 12", "rating": 16.5, "apr": 984, "brand": 9, "city": "Norman", "state": "OK", "lat": 35.21, "lon": -97.44, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 2},
        {"id": "louisville", "name": "Louisville", "conf": "ACC", "rating": 11.0, "apr": 983, "brand": 7, "city": "Louisville", "state": "KY", "lat": 38.21, "lon": -85.76, "wins": 9, "losses": 1, "conf_wins": 6, "conf_losses": 1},
        {"id": "arizona", "name": "Arizona", "conf": "Pac-12", "rating": 13.0, "apr": 978, "brand": 6, "city": "Tucson", "state": "AZ", "lat": 32.23, "lon": -110.95, "wins": 7, "losses": 3, "conf_wins": 5, "conf_losses": 2, "legacy_pac12": True},
        {"id": "notre_dame", "name": "Notre Dame", "conf": "Independent", "rating": 18.5, "apr": 994, "brand": 10, "city": "Notre Dame", "state": "IN", "lat": 41.70, "lon": -86.23, "wins": 7, "losses": 3, "conf_wins": 0, "conf_losses": 0, "acc_bowl_eligible": True},
        {"id": "iowa", "name": "Iowa", "conf": "Big Ten", "rating": 8.0, "apr": 985, "brand": 7, "city": "Iowa City", "state": "IA", "lat": 41.66, "lon": -91.54, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 2},
        {"id": "oklahoma_state", "name": "Oklahoma State", "conf": "Big 12", "rating": 9.5, "apr": 982, "brand": 7, "city": "Stillwater", "state": "OK", "lat": 36.12, "lon": -97.06, "wins": 7, "losses": 3, "conf_wins": 5, "conf_losses": 2},
        {"id": "tennessee", "name": "Tennessee", "conf": "SEC", "rating": 12.0, "apr": 978, "brand": 9, "city": "Knoxville", "state": "TN", "lat": 35.95, "lon": -83.92, "wins": 7, "losses": 3, "conf_wins": 3, "conf_losses": 3},
        {"id": "kansas_state", "name": "Kansas State", "conf": "Big 12", "rating": 13.5, "apr": 982, "brand": 7, "city": "Manhattan", "state": "KS", "lat": 39.19, "lon": -96.58, "wins": 7, "losses": 3, "conf_wins": 5, "conf_losses": 2},
        {"id": "nc_state", "name": "NC State", "conf": "ACC", "rating": 8.5, "apr": 982, "brand": 6, "city": "Raleigh", "state": "NC", "lat": 35.79, "lon": -78.68, "wins": 7, "losses": 3, "conf_wins": 4, "conf_losses": 2},
        {"id": "liberty", "name": "Liberty", "conf": "CUSA", "rating": 7.0, "apr": 982, "brand": 5, "city": "Lynchburg", "state": "VA", "lat": 37.35, "lon": -79.18, "wins": 10, "losses": 0, "conf_wins": 7, "conf_losses": 0},
        {"id": "tulane", "name": "Tulane", "conf": "AAC", "rating": 5.5, "apr": 989, "brand": 6, "city": "New Orleans", "state": "LA", "lat": 29.94, "lon": -90.12, "wins": 9, "losses": 1, "conf_wins": 6, "conf_losses": 0},
        {"id": "smu", "name": "SMU", "conf": "AAC", "rating": 9.0, "apr": 984, "brand": 6, "city": "Dallas", "state": "TX", "lat": 32.84, "lon": -96.78, "wins": 8, "losses": 2, "conf_wins": 6, "conf_losses": 0},
        {"id": "clemson", "name": "Clemson", "conf": "ACC", "rating": 12.5, "apr": 995, "brand": 9, "city": "Clemson", "state": "SC", "lat": 34.68, "lon": -82.84, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4},
        {"id": "texas_am", "name": "Texas A&M", "conf": "SEC", "rating": 12.0, "apr": 977, "brand": 9, "city": "College Station", "state": "TX", "lat": 30.61, "lon": -96.34, "wins": 6, "losses": 4, "conf_wins": 4, "conf_losses": 3},
        {"id": "wisconsin", "name": "Wisconsin", "conf": "Big Ten", "rating": 7.5, "apr": 987, "brand": 7, "city": "Madison", "state": "WI", "lat": 43.07, "lon": -89.41, "wins": 5, "losses": 5, "conf_wins": 3, "conf_losses": 4},
        {"id": "kentucky", "name": "Kentucky", "conf": "SEC", "rating": 6.5, "apr": 981, "brand": 6, "city": "Lexington", "state": "KY", "lat": 38.03, "lon": -84.50, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4},
        {"id": "west_virginia", "name": "West Virginia", "conf": "Big 12", "rating": 6.0, "apr": 981, "brand": 6, "city": "Morgantown", "state": "WV", "lat": 39.63, "lon": -79.95, "wins": 6, "losses": 4, "conf_wins": 4, "conf_losses": 3},
        {"id": "north_carolina", "name": "North Carolina", "conf": "ACC", "rating": 9.0, "apr": 981, "brand": 7, "city": "Chapel Hill", "state": "NC", "lat": 35.90, "lon": -79.05, "wins": 8, "losses": 2, "conf_wins": 4, "conf_losses": 2},
        {"id": "maryland", "name": "Maryland", "conf": "Big Ten", "rating": 6.5, "apr": 980, "brand": 6, "city": "College Park", "state": "MD", "lat": 38.99, "lon": -76.94, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4},
        {"id": "auburn", "name": "Auburn", "conf": "SEC", "rating": 8.0, "apr": 980, "brand": 8, "city": "Auburn", "state": "AL", "lat": 32.60, "lon": -85.49, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4},
        {"id": "oregon_state", "name": "Oregon State", "conf": "Pac-12", "rating": 14.0, "apr": 983, "brand": 6, "city": "Corvallis", "state": "OR", "lat": 44.56, "lon": -123.28, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 2, "legacy_pac12": True},
        {"id": "memphis", "name": "Memphis", "conf": "AAC", "rating": 3.0, "apr": 982, "brand": 6, "city": "Memphis", "state": "TN", "lat": 35.12, "lon": -89.94, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 1},
        {"id": "iowa_state", "name": "Iowa State", "conf": "Big 12", "rating": 6.5, "apr": 986, "brand": 6, "city": "Ames", "state": "IA", "lat": 42.02, "lon": -93.64, "wins": 6, "losses": 4, "conf_wins": 5, "conf_losses": 2},
        {"id": "rutgers", "name": "Rutgers", "conf": "Big Ten", "rating": 4.5, "apr": 988, "brand": 6, "city": "Piscataway", "state": "NJ", "lat": 40.52, "lon": -74.46, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4},
        {"id": "miami", "name": "Miami (FL)", "conf": "ACC", "rating": 8.5, "apr": 980, "brand": 8, "city": "Coral Gables", "state": "FL", "lat": 25.72, "lon": -80.28, "wins": 6, "losses": 4, "conf_wins": 2, "conf_losses": 4},
        {"id": "northwestern", "name": "Northwestern", "conf": "Big Ten", "rating": 2.0, "apr": 996, "brand": 5, "city": "Evanston", "state": "IL", "lat": 42.06, "lon": -87.67, "wins": 5, "losses": 5, "conf_wins": 3, "conf_losses": 4},
        {"id": "utah", "name": "Utah", "conf": "Pac-12", "rating": 10.5, "apr": 987, "brand": 7, "city": "Salt Lake City", "state": "UT", "lat": 40.76, "lon": -111.85, "wins": 7, "losses": 3, "conf_wins": 4, "conf_losses": 3, "legacy_pac12": True},
        {"id": "usc", "name": "USC", "conf": "Pac-12", "rating": 10.0, "apr": 979, "brand": 9, "city": "Los Angeles", "state": "CA", "lat": 34.02, "lon": -118.29, "wins": 7, "losses": 4, "conf_wins": 5, "conf_losses": 3, "legacy_pac12": True},
        {"id": "kansas", "name": "Kansas", "conf": "Big 12", "rating": 7.0, "apr": 980, "brand": 6, "city": "Lawrence", "state": "KS", "lat": 38.96, "lon": -95.25, "wins": 7, "losses": 3, "conf_wins": 4, "conf_losses": 3},
        {"id": "unlv", "name": "UNLV", "conf": "MWC", "rating": 3.0, "apr": 976, "brand": 5, "city": "Las Vegas", "state": "NV", "lat": 36.11, "lon": -115.14, "wins": 8, "losses": 2, "conf_wins": 5, "conf_losses": 1},
        {"id": "ucla", "name": "UCLA", "conf": "Pac-12", "rating": 6.5, "apr": 982, "brand": 7, "city": "Pasadena", "state": "CA", "lat": 34.07, "lon": -118.44, "wins": 6, "losses": 4, "conf_wins": 3, "conf_losses": 4, "legacy_pac12": True},
        {"id": "boise_state", "name": "Boise State", "conf": "MWC", "rating": 4.5, "apr": 984, "brand": 7, "city": "Boise", "state": "ID", "lat": 43.60, "lon": -116.20, "wins": 5, "losses": 5, "conf_wins": 4, "conf_losses": 2},
    ]

    # Remaining games Weeks 12-13
    schedule = [
        {"home": "michigan", "away": "ohio_state", "neutral": False, "conf": True},
        {"home": "auburn", "away": "alabama", "neutral": False, "conf": True},
        {"home": "georgia", "away": "tennessee", "neutral": False, "conf": True},
        {"home": "oregon_state", "away": "washington", "neutral": False, "conf": True},
        {"home": "oregon", "away": "oregon_state", "neutral": False, "conf": True},
        {"home": "washington", "away": "washington_state", "neutral": False, "conf": False},
        {"home": "texas", "away": "texas_tech", "neutral": False, "conf": True},
        {"home": "florida", "away": "florida_state", "neutral": False, "conf": False},
        {"home": "lsu", "away": "texas_am", "neutral": False, "conf": True},
        {"home": "clemson", "away": "north_carolina", "neutral": False, "conf": True},
        {"home": "south_carolina", "away": "clemson", "neutral": False, "conf": False},
    ]

    # Ground truth actual 2023 bowl assignments
    actual_assignments = {
        "rose_bowl": ["michigan", "alabama"],
        "sugar_bowl": ["washington", "texas"],
        "orange_bowl": ["georgia", "florida_state"],
        "cotton_bowl": ["missouri", "ohio_state"],
        "peach_bowl": ["ole_miss", "penn_state"],
        "fiesta_bowl": ["oregon", "liberty"],
        "citrus_bowl": ["tennessee", "iowa"],
        "reliaquest_bowl": ["lsu", "wisconsin"],
        "alamo_bowl": ["arizona", "oklahoma"],
        "pop_tarts_bowl": ["kansas_state", "nc_state"],
        "texas_bowl": ["oklahoma_state", "texas_am"],
        "gator_bowl": ["clemson", "kentucky"],
        "dukes_mayo_bowl": ["west_virginia", "north_carolina"],
        "music_city_bowl": ["maryland", "auburn"],
        "sun_bowl": ["notre_dame", "oregon_state"],
        "liberty_bowl": ["memphis", "iowa_state"],
        "pinstripe_bowl": ["rutgers", "miami"],
        "las_vegas_bowl": ["northwestern", "utah"],
        "holiday_bowl": ["usc", "louisville"],
        "guaranteed_rate_bowl": ["kansas", "unlv"],
        "la_bowl": ["ucla", "boise_state"],
    }

    with open(DIR / "teams_2023.json", "w") as f:
        json.dump(teams, f, indent=2)
    with open(DIR / "schedule_2023.json", "w") as f:
        json.dump(schedule, f, indent=2)
    with open(DIR / "actual_assignments_2023.json", "w") as f:
        json.dump(actual_assignments, f, indent=2)

    print("2023 backtest data generated successfully.")

if __name__ == "__main__":
    build_2023()
