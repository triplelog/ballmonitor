"""Birthplace -> latitude/longitude for every player in the Lahman database.

Lahman gives a birth city, a state/province and a country, no coordinates. They are matched to
GeoNames (CC BY 4.0, download.geonames.org/export/dump):
GeoNames' full country file for each country in the Americas (every populated place, feature
class P, incl. historical and abandoned towns; alternate names for renamed towns), matched by
country + state/province + name (US, Canada) or country + name with the player's province
preferred (elsewhere). When no town matches, a county or a military base of that name is used
("Maury County, TN", "Fort Sill, OK").
Names are compared after removing accents and punctuation ("St." = "Saint", "Ft." = "Fort").
Among several places with the same name, the one in the player's province wins, then the
biggest. Players with no birthplace, or one that matches nothing, are listed in the build
report and left off the maps (never guessed).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

# Lahman birthCountry -> ISO code; only countries a map frame could reach (the Americas).
COUNTRIES = {
    "USA": "US", "P.R.": "PR", "CAN": "CA", "D.R.": "DO", "Cuba": "CU", "Venezuela": "VE", "México": "MX",
    "Mexico": "MX", "Panama": "PA", "Colombia": "CO", "Curaçao": "CW", "Nicaragua": "NI",
    "U.S. Virgin Islands": "VI", "Bahamas": "BS", "Aruba": "AW", "Jamaica": "JM", "Honduras": "HN",
    "British Honduras": "BZ", "Belize": "BZ", "Brazil": "BR", "Peru": "PE", "Haiti": "HT", "Guatemala": "GT",
    "El Salvador": "SV", "Costa Rica": "CR", "Bermuda": "BM", "Trinidad and Tobago": "TT",
    "Netherlands Antilles": "CW", "Saint Kitts and Nevis": "KN", "Virgin Islands": "VI",
}
CA_PROVINCES = {"AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NF": "05", "NS": "07",
                "ON": "08", "PE": "09", "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14"}
# Lahman names that GeoNames spells differently (normalised forms)
ALIASES = {("US", "NY", "new york"): "new york city"}
FEATURE_RANK = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3, "PPLA4": 4, "PPL": 5, "PPLX": 6, "PPLL": 7,
                "PPLF": 8, "PPLS": 8, "PPLH": 9, "PPLQ": 9, "PPLW": 9}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\bst\.?\s", "saint ", s)
    s = re.sub(r"\bste\.?\s", "sainte ", s)
    s = re.sub(r"\bft\.?\s", "fort ", s)
    s = re.sub(r"\bmt\.?\s", "mount ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _province_norm(name: str) -> str:
    s = norm(name)
    for w in (" province", " provincia", "provincia de ", "distrito "):
        s = s.replace(w, " ")
    return re.sub(r"\s+", " ", s).strip()


FALLBACK_CODES = {"ADM2", "ADM3", "MILB", "INSM", "AIRB"}   # a county or a base, when no town matches


def _keys(name: str) -> set[str]:
    n = norm(name)
    out = {n, n.replace(" ", "")}
    if n.startswith("the "):
        out |= {n[4:], n[4:].replace(" ", "")}
    return out - {""}


class Gazetteer:
    """Index of GeoNames places: (country, admin1 or "", name) -> [(fallback?, -pop, rank, lat, lon,
    label, admin1)]. One full GeoNames country file per country in COUNTRIES (data/raw/geonames/<CC>/)."""

    def __init__(self, raw: Path):
        self.by_key: dict[tuple, list] = {}
        self.admin1: dict[str, str] = {}   # "DO.24" -> normalised name
        for line in (raw / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
            code, name, ascii_name, _ = line.split("\t")
            self.admin1[code] = _province_norm(ascii_name)
        for cc in sorted(set(COUNTRIES.values())):
            path = raw / cc / f"{cc}.txt"
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    f = line.rstrip("\n").split("\t")
                    fallback = f[7] in FALLBACK_CODES
                    if f[6] != "P" and not fallback:
                        continue
                    rank = FEATURE_RANK.get(f[7], 8)
                    pop = int(f[14] or 0)
                    entry = (fallback, rank > 6, -pop, rank, float(f[4]), float(f[5]), f"{f[1]}, {f[10]}, {cc}", f[10])
                    names = _keys(f[1]) | _keys(f[2])
                    alts = [a for a in f[3].split(",") if a and a.isascii()][:25]
                    for a in alts:   # renamed or respelled towns (Lake Worth, Ciudad Trujillo)
                        names |= _keys(a)
                    for n in names:
                        self.by_key.setdefault((cc, f[10], n), []).append(entry)
                        if cc not in ("US", "CA"):
                            self.by_key.setdefault((cc, "", n), []).append(entry)

    def find(self, cc: str, state: str, city: str) -> tuple[float, float, str, int] | None:
        """(lat, lon, matched place, its GeoNames population) or None."""
        n = norm(city)
        if not n:
            return None
        n = ALIASES.get((cc, state, n), n)
        for key in dict.fromkeys((n, n.replace(" ", ""))):
            hits = self._lookup(cc, state, key)
            if hits:
                best = min(hits)
                return best[4], best[5], best[6], -best[2]
        return None

    def _lookup(self, cc: str, state: str, n: str) -> list | None:
        if cc == "US":
            return self.by_key.get(("US", state, n))
        if cc == "CA":
            return self.by_key.get(("CA", CA_PROVINCES.get(state, ""), n))
        hits: list = []
        want = _province_norm(state) if state else ""
        if want:   # prefer the place in the player's province
            for c, v in self.admin1.items():
                if c.startswith(cc + ".") and (v == want or want in v or v in want):
                    hits += self.by_key.get((cc, c.split(".")[1], n), [])
        return hits or self.by_key.get((cc, "", n))


def geocode(people_csv: Path, raw: Path) -> tuple[list[dict], dict]:
    """Every Lahman player -> {playerID, lat, lon, place, status}; status: matched | no_place |
    off_map (a country no frame reaches) | unmatched."""
    gaz = Gazetteer(raw)
    out, counts = [], {"matched": 0, "no_place": 0, "off_map": 0, "unmatched": 0}
    with people_csv.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cc = COUNTRIES.get(r["birthCountry"])
            row = {"playerID": r["playerID"], "lat": "", "lon": "", "place": "", "place_pop": 0, "status": ""}
            if not r["birthCountry"] or not r["birthCity"]:
                row["status"] = "no_place"
            elif cc is None:
                row["status"] = "off_map"
            else:
                state, city = r["birthState"], r["birthCity"]
                if cc == "US" and state == "CZ":   # the Panama Canal Zone
                    cc, state = "PA", ""
                hit = gaz.find(cc, state, city)
                m = re.search(r"([A-Z][\w.' ]*? County)$", city)
                if not hit and m:   # "Corydon Township Warren County" -> the county
                    hit = gaz.find(cc, state, m.group(1).split(" Township ")[-1].strip())
                if hit:
                    row.update(lat=round(hit[0], 4), lon=round(hit[1], 4), place=hit[2], place_pop=hit[3], status="matched")
                else:
                    row["status"] = "unmatched"
                    row["place"] = f"{r['birthCity']}, {r['birthState']}, {r['birthCountry']}"
            counts[row["status"]] += 1
            out.append(row)
    return out, counts
