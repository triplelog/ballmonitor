import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Recruit
from .geocoding import CityLocator

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Standard normalization map for collegiate program names across Rivals / FEI / AP datasets
SCHOOL_ALIASES = {
    "miami": "Miami (FL)",
    "miami (fl)": "Miami (FL)",
    "miami-florida": "Miami (FL)",
    "miami (ohio)": "Miami (OH)",
    "miami (oh)": "Miami (OH)",
    "texas a&m": "Texas A&M",
    "texas au0026m": "Texas A&M",
    "byu": "BYU",
    "brigham young": "BYU",
    "central florida": "UCF",
    "ucf": "UCF",
    "louisiana lafayette": "Louisiana",
    "louisiana-lafayette": "Louisiana",
    "louisiana": "Louisiana",
    "ull": "Louisiana",
    "smu": "SMU",
    "southern methodist": "SMU",
    "ole miss": "Ole Miss",
    "mississippi": "Ole Miss",
    "nc state": "NC State",
    "n.c. state": "NC State",
    "north carolina state": "NC State",
    "southern mississippi": "Southern Miss",
    "southern miss": "Southern Miss",
    "ul monroe": "Louisiana-Monroe",
    "ul-monroe": "Louisiana-Monroe",
    "louisiana monroe": "Louisiana-Monroe",
    "louisiana-monroe": "Louisiana-Monroe",
    "middle tennessee": "Middle Tennessee State",
    "middle tennessee state": "Middle Tennessee State",
    "uconn": "Connecticut",
    "connecticut": "Connecticut",
    "pittsburgh": "Pitt",
    "pitt": "Pitt",
    "hawaii": "Hawai'i",
    # Spellings that differ between the legacy Rivals files, On3 and ESPN (v0.4.0)
    "usf": "South Florida",
    "south florida": "South Florida",
    "fiu": "FIU",
    "florida international": "FIU",
    "florida intl": "FIU",
    "ut san antonio": "UTSA",
    "utsa": "UTSA",
    "san josé st": "San Jose State",
    "san josé state": "San Jose State",
    "umass": "Massachusetts",
    "app state": "Appalachian State",
    "long island university": "Long Island",  # MBB (v0.5.0)
}

# Destinations On3 lists like schools but which are not college programs (MBB recruits
# who turned pro). Commits to them are treated as "no college commitment" and they are
# dropped from offer lists, so they never appear in the class rankings (v0.5.0).
NON_COLLEGE = {"NBA G League", "Professional", "Overtime", "Overtime Elite"}


def normalize_team(name: str) -> str:
    """Normalize team names to canonical representations."""
    cleaned = name.strip()
    lowered = cleaned.lower()
    return SCHOOL_ALIASES.get(lowered, cleaned)


def standardize_team_name(team_name: str, team_slug: str = "") -> str:
    """Normalize team names to match the model's standardized FBS campus names."""
    name = (team_name or "").strip()
    slug = (team_slug or "").lower()

    if name == "Miami":
        if "hurricanes" in slug or "fl" in slug:
            return "Miami (FL)"
        elif "redhawks" in slug or "oh" in slug:
            return "Miami (OH)"
    elif name == "NC State" or "north-carolina-state" in slug:
        return "NC State"
    elif name == "Ole Miss" or "ole-miss" in slug:
        return "Ole Miss"
    elif name == "USC" or "southern-california" in slug:
        return "USC"
    elif name == "LSU" or "louisiana-state" in slug:
        return "LSU"
    elif name == "UCF" or "central-florida" in slug:
        return "UCF"
    elif name == "BYU" or "brigham-young" in slug:
        return "BYU"

    return name


class DataLoader:
    """Handles reading and normalizing recruiting, ranking, and validation datasets."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.locator: Optional[CityLocator] = None

    def _get_locator(self) -> CityLocator:
        if self.locator is None:
            cities_csv = self.data_dir / "reference" / "uscities.csv"
            self.locator = CityLocator(cities_csv)
        return self.locator

    def load_recruits(
        self,
        year: int,
        geolocate: bool = False,
        include_uncommitted: bool = False,
        sport: str = "ncaaf",
    ) -> List[Recruit]:
        """Load all recruit profiles and scholarship offers for a given season and sport."""
        raw_records = _load_raw_recruits_cached(
            str(self.data_dir.resolve()), year, geolocate, include_uncommitted, sport.lower()
        )
        return [
            Recruit(
                url=r[0],
                year=r[1],
                name=r[2],
                position=r[3],
                hometown=r[4],
                stars=r[5],
                committed_team=r[6],
                offers=list(r[7]),
                latitude=r[8],
                longitude=r[9],
            )
            for r in raw_records
        ]

    def load_rivals_rankings(self, year: int) -> Dict[str, Tuple[int, float]]:
        """Load Rivals official team rankings: returns {team_name: (rank, points)}."""
        file_path = self.data_dir / "teams" / f"football{year}.csv"
        if not file_path.exists():
            return {}

        rankings: Dict[str, Tuple[int, float]] = {}
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 3:
                    continue
                try:
                    rank = int(row[0].strip())
                    team = normalize_team(row[1].strip())
                    pts = float(row[2].strip())
                    rankings[team] = (rank, pts)
                except ValueError:
                    continue
        return rankings

    def load_fei_ratings(self, year: int) -> Dict[str, float]:
        """Load Football Outsiders FEI ratings for a given season: returns {team_name: fei}."""
        file_path = self.data_dir / "analysis" / f"{year}FBO.csv"
        if not file_path.exists():
            return {}

        fei_map: Dict[str, float] = {}
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) < 4:
                    continue
                team = normalize_team(row[1].strip())
                try:
                    val = float(row[3].strip())
                    fei_map[team] = val
                except ValueError:
                    continue
        return fei_map

    def load_conferences(self) -> Dict[str, str]:
        """Load conference affiliations map {team_name: conference_name}."""
        file_path = self.data_dir / "reference" / "conflist.csv"
        if not file_path.exists():
            return {}

        confs: Dict[str, str] = {}
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    team = normalize_team(row[0].strip())
                    confs[team] = row[1].strip()
        return confs


@lru_cache(maxsize=64)
def _get_cached_locator(cities_csv_str: str) -> CityLocator:
    return CityLocator(Path(cities_csv_str))


@lru_cache(maxsize=64)
def _load_raw_recruits_cached(
    data_dir_str: str,
    year: int,
    geolocate: bool,
    include_uncommitted: bool,
    sport: str = "ncaaf",
) -> Tuple[Tuple[str, int, str, str, str, int, str, Tuple[str, ...], float, float], ...]:
    data_dir = Path(data_dir_str)
    if sport == "mbb":
        file_path = data_dir / "recruits" / f"recruits_mbb_{year}.csv"
    elif sport == "wbb":
        file_path = data_dir / "recruits" / f"recruits_wbb_{year}.csv"
    else:
        file_path = data_dir / "recruits" / f"football{year}done.csv"

    if not file_path.exists():
        raise FileNotFoundError(f"Recruit data not found for {sport.upper()} {year}: {file_path}")

    records = []
    locator = _get_cached_locator(str(data_dir / "reference" / "uscities.csv")) if geolocate else None

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 7:
                continue

            url = row[0].strip()
            try:
                yr = int(row[1])
            except ValueError:
                yr = year

            name = row[2].strip()
            position = row[3].strip()
            hometown = row[4].strip()

            try:
                stars = int(row[5])
            except ValueError:
                stars = 0

            raw_committed = row[6].strip()
            if raw_committed in NON_COLLEGE:
                raw_committed = ""
            if not raw_committed or raw_committed == "0":
                if not include_uncommitted:
                    continue
                committed_team = ""
            else:
                committed_team = normalize_team(raw_committed)

            offers: List[str] = []
            for team_str in row[7:]:
                cleaned = team_str.strip()
                if cleaned and cleaned != "0" and cleaned not in NON_COLLEGE:
                    norm = normalize_team(cleaned)
                    if norm != committed_team and norm not in offers:
                        offers.append(norm)

            lat, lon = (0.0, 0.0)
            if locator and hometown:
                lat, lon = locator.locate(hometown)

            records.append(
                (url, yr, name, position, hometown, stars, committed_team, tuple(offers), lat, lon)
            )

    return tuple(records)
