import csv
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import Levenshtein as pl
    HAS_LEVENSHTEIN = True
except ImportError:
    HAS_LEVENSHTEIN = False


def pure_levenshtein_distance(s1: str, s2: str) -> int:
    """Pure-Python Levenshtein distance fallback when C library is unavailable."""
    if len(s1) < len(s2):
        return pure_levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def str_distance(s1: str, s2: str) -> int:
    if HAS_LEVENSHTEIN:
        return pl.distance(s1, s2)
    return pure_levenshtein_distance(s1, s2)


class CityLocator:
    """Resolves US city and state names to latitude and longitude coordinates."""

    def __init__(self, cities_csv_path: Optional[Path] = None):
        self.state_cities: Dict[str, Dict[str, Tuple[float, float]]] = {}
        if cities_csv_path and Path(cities_csv_path).exists():
            self._load_cities(Path(cities_csv_path))

    def _load_cities(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) < 8:
                    continue
                city_name = row[1].strip()
                state_code = row[2].strip()
                try:
                    lat = float(row[6])
                    lng = float(row[7])
                except (ValueError, IndexError):
                    continue

                if state_code not in self.state_cities:
                    self.state_cities[state_code] = {}
                self.state_cities[state_code][city_name] = (lat, lng)

    def locate(self, hometown_str: str) -> Tuple[float, float]:
        """Convert 'City, ST' string to (latitude, longitude)."""
        if not hometown_str or "," not in hometown_str:
            return (0.0, 0.0)

        parts = hometown_str.split(",")
        if len(parts) != 2:
            return (0.0, 0.0)

        city = parts[0].strip()
        state = parts[1].strip()

        if state not in self.state_cities:
            return (0.0, 0.0)

        state_dict = self.state_cities[state]
        if city in state_dict:
            return state_dict[city]

        # Case-insensitive match
        city_lower = city.lower()
        for c, coords in state_dict.items():
            if c.lower() == city_lower:
                return coords

        # Nearest string distance match
        min_d = -1
        best_coords = (0.0, 0.0)
        for c, coords in state_dict.items():
            d = str_distance(c.lower(), city_lower)
            if min_d == -1 or d < min_d:
                min_d = d
                best_coords = coords
            if min_d == 0:
                break

        return best_coords if min_d <= 4 else (0.0, 0.0)


def haversine_miles(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """Calculate the great-circle distance between two points in miles."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    if (lat1 == 0.0 and lon1 == 0.0) or (lat2 == 0.0 and lon2 == 0.0):
        return 0.0

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    radius_earth_miles = 3958.8
    return radius_earth_miles * c


# Comprehensive campus coordinates for FBS & major collegiate football programs
CAMPUS_COORDINATES: Dict[str, Tuple[float, float]] = {
    "Alabama": (33.2140, -87.5391),
    "Auburn": (32.6010, -85.4853),
    "UAB": (33.5019, -86.8055),
    "South Alabama": (30.6954, -88.1794),
    "Troy": (31.7996, -85.9567),
    "Arkansas": (36.0687, -94.1748),
    "Arkansas State": (35.8427, -90.6756),
    "Arizona": (32.2319, -110.9501),
    "Arizona State": (33.4242, -111.9281),
    "California": (37.8719, -122.2585),
    "Stanford": (37.4275, -122.1697),
    "UCLA": (34.0689, -118.4452),
    "USC": (34.0224, -118.2851),
    "Fresno State": (36.8144, -119.7462),
    "San Diego State": (32.7753, -117.0713),
    "San Jose State": (37.3352, -121.8811),
    "Colorado": (40.0073, -105.2660),
    "Colorado State": (40.5734, -105.0865),
    "Air Force": (38.9984, -104.8614),
    "Connecticut": (41.8077, -72.2495),
    "Florida": (29.6436, -82.3549),
    "Florida State": (30.4419, -84.2985),
    "Miami (FL)": (25.7174, -80.2782),
    "UCF": (28.6024, -81.2001),
    "USF": (28.0587, -82.4139),
    "FAU": (26.3712, -80.1017),
    "FIU": (25.7562, -80.3764),
    "Georgia": (33.9480, -83.3773),
    "Georgia Tech": (33.7756, -84.3980),
    "Georgia Southern": (32.4211, -81.7860),
    "Georgia State": (33.7531, -84.3853),
    "Hawai'i": (21.3000, -157.8162),
    "Iowa": (41.6627, -91.5365),
    "Iowa State": (42.0266, -93.6465),
    "Boise State": (43.6029, -116.1994),
    "Idaho": (46.7265, -117.0125),
    "Illinois": (40.1020, -88.2272),
    "Northwestern": (42.0565, -87.6753),
    "Northern Illinois": (41.9345, -88.7744),
    "Indiana": (39.1670, -86.5233),
    "Notre Dame": (41.7056, -86.2353),
    "Purdue": (40.4237, -86.9212),
    "Ball State": (40.2001, -85.4082),
    "Kansas": (38.9543, -95.2558),
    "Kansas State": (39.1974, -96.5847),
    "Kentucky": (38.0307, -84.5040),
    "Louisville": (38.2123, -85.7585),
    "Western Kentucky": (36.9854, -86.4558),
    "LSU": (30.4133, -91.1800),
    "Louisiana": (30.2144, -92.0198),
    "Louisiana Tech": (32.5290, -92.6514),
    "Louisiana-Monroe": (32.5283, -92.0664),
    "Tulane": (29.9407, -90.1203),
    "Boston College": (42.3355, -71.1685),
    "UMass": (42.3868, -72.5301),
    "Maryland": (38.9869, -76.9426),
    "Navy": (38.9830, -76.4850),
    "Michigan": (42.2780, -83.7382),
    "Michigan State": (42.7018, -84.4842),
    "Central Michigan": (43.5900, -84.7760),
    "Eastern Michigan": (42.2510, -83.6240),
    "Western Michigan": (42.2830, -85.6150),
    "Minnesota": (44.9740, -93.2277),
    "Missouri": (38.9404, -92.3277),
    "Ole Miss": (34.3647, -89.5384),
    "Mississippi State": (33.4552, -88.7944),
    "Southern Miss": (31.3293, -89.3334),
    "North Carolina": (35.9049, -79.0469),
    "NC State": (35.7847, -78.6821),
    "Duke": (36.0014, -78.9382),
    "Wake Forest": (36.1344, -80.2784),
    "East Carolina": (35.6068, -77.3665),
    "Appalachian State": (36.2140, -81.6780),
    "Charlotte": (35.3071, -80.7352),
    "Nebraska": (40.8202, -96.7005),
    "Nevada": (39.5437, -119.8157),
    "UNLV": (36.1075, -115.1430),
    "Rutgers": (40.5230, -74.4580),
    "New Mexico": (35.0844, -106.6190),
    "New Mexico State": (32.2796, -106.7512),
    "Syracuse": (43.0392, -76.1351),
    "Army": (41.3918, -73.9580),
    "Buffalo": (43.0008, -78.7890),
    "Ohio State": (40.0067, -83.0305),
    "Cincinnati": (39.1329, -84.5150),
    "Akron": (41.0754, -81.5122),
    "Bowling Green": (41.3781, -83.6264),
    "Kent State": (41.1490, -81.3430),
    "Miami (OH)": (39.5090, -84.7340),
    "Ohio": (39.3242, -82.1013),
    "Toledo": (41.6580, -83.6140),
    "Oklahoma": (35.2059, -97.4457),
    "Oklahoma State": (36.1264, -97.0734),
    "Tulsa": (36.1524, -95.9461),
    "Oregon": (44.0448, -123.0726),
    "Oregon State": (44.5638, -123.2794),
    "Penn State": (40.7982, -77.8599),
    "Pitt": (40.4444, -79.9608),
    "Temple": (39.9812, -75.1566),
    "Clemson": (34.6834, -82.8374),
    "South Carolina": (33.9961, -81.0274),
    "Coastal Carolina": (33.7944, -79.0142),
    "Tennessee": (35.9544, -83.9295),
    "Vanderbilt": (36.1447, -86.8027),
    "Memphis": (35.1186, -89.9373),
    "Middle Tennessee State": (35.8486, -86.3681),
    "Texas": (30.2849, -97.7341),
    "Texas A&M": (30.6187, -96.3365),
    "Baylor": (31.5482, -97.1189),
    "TCU": (32.7079, -97.3628),
    "Texas Tech": (33.5843, -101.8783),
    "Houston": (29.7199, -95.3422),
    "SMU": (32.8412, -96.7845),
    "North Texas": (33.2075, -97.1526),
    "Rice": (29.7174, -95.4018),
    "Texas State": (29.8884, -97.9404),
    "UTSA": (29.5840, -98.6180),
    "UTEP": (31.7700, -106.5050),
    "Utah": (40.7649, -111.8500),
    "BYU": (40.2518, -111.6493),
    "Utah State": (41.7452, -111.8100),
    "Virginia": (38.0336, -78.5080),
    "Virginia Tech": (37.2284, -80.4234),
    "Old Dominion": (36.8853, -76.3059),
    "Washington": (47.6553, -122.3035),
    "Washington State": (46.7319, -117.1542),
    "Wisconsin": (43.0766, -89.4012),
    "West Virginia": (39.6360, -79.9550),
    "Marshall": (38.4230, -82.4240),
    "Wyoming": (41.3140, -105.5810),
}


def get_campus_coords(team_name: str) -> Optional[Tuple[float, float]]:
    """Return (latitude, longitude) for a collegiate program campus."""
    return CAMPUS_COORDINATES.get(team_name)
