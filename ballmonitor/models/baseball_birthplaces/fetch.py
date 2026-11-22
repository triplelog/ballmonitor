"""Build the birthplace maps' data (by hand: needs the ~2 GB raw downloads below).

    ballmonitor fetch baseball_birthplaces [--offline]

Raw inputs (data/raw/, gitignored; --offline uses what is there):
  isimip/   ISIMIP3a historical population, 5 arc-minutes, annual 1850-2021 (from HYDE 3.2):
            files.isimip.org/ISIMIP3a/InputData/socioeconomic/pop/histsoc/population_histsoc_5arcmin_annual_*.nc
  geonames/ GeoNames country files (US, CA, PR, DO, VE, CU, MX, ...), admin1CodesASCII.txt (CC BY 4.0)
  natural-earth/  Natural Earth 1:50m admin 0 countries + admin 1 states/provinces (public domain)
  Lahman CSVs: ballmonitor/games/triple_play/data/raw/lahman_csv/ (Triple Play's copy)

Writes (data/, committed):
  players.csv     every placed player: birthplace (lat/lon, matched place), birth year, career totals
  unplaced.csv    players left off the maps and why
  grid/<decade>_<frame>.png   circle radius per map cell (engine.png_bytes), one per birth decade
  grid/<decade>_<frame>_people.png   the population inside each stored circle (units of 50): the
                exact per-capita divisor
  grid/<decade>_<frame>_pop.png   people per map cell (log1p x 4000), for regions a visitor draws
  grid/meta.json  frames, decades, population year per decade, counts
  borders.json    country and state outlines per frame (projected km, simplified)
"""

from __future__ import annotations

import csv
import io
import json
import math
import struct
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from ballmonitor.core import registry

from . import engine as E
from .geocode import COUNTRIES, geocode

ISIMIP = "https://files.isimip.org/ISIMIP3a/InputData/socioeconomic/pop/histsoc/"
POP_FILES = ("population_histsoc_5arcmin_annual_1850_1900.nc", "population_histsoc_5arcmin_annual_1901_2021.nc")
GEONAMES = "https://download.geonames.org/export/dump/"
NATURAL_EARTH = "https://naciscdn.org/naturalearth/50m/cultural/"
NE_FILES = ("ne_50m_admin_0_countries_lakes", "ne_50m_admin_1_states_provinces_lakes")
LAHMAN = Path(__file__).resolve().parents[2] / "games" / "triple_play" / "data" / "raw" / "lahman_csv"


def _download(url: str, dest: Path, offline: bool) -> None:
    if dest.exists() or offline:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ballmonitor data build"})
    with urllib.request.urlopen(req, timeout=600) as r, dest.open("wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)


def raw_inputs(raw: Path, offline: bool) -> None:
    for f in POP_FILES:
        _download(ISIMIP + f, raw / "isimip" / f, offline)
    for cc in sorted(set(COUNTRIES.values())):
        z = raw / "geonames" / f"{cc}.zip"
        _download(f"{GEONAMES}{cc}.zip", z, offline)
        if z.exists() and not (raw / "geonames" / cc / f"{cc}.txt").exists():
            zipfile.ZipFile(z).extractall(raw / "geonames" / cc)
    _download(GEONAMES + "admin1CodesASCII.txt", raw / "geonames" / "admin1CodesASCII.txt", offline)
    for name in NE_FILES:
        z = raw / "natural-earth" / f"{name}.zip"
        _download(f"{NATURAL_EARTH}{name}.zip", z, offline)
        if z.exists() and not (raw / "natural-earth" / f"{name}.shp").exists():
            zipfile.ZipFile(z).extractall(raw / "natural-earth")


# ------------------------------------------------------------------------- careers

def _rows(name: str):
    with (LAHMAN / f"{name}.csv").open(newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


def _i(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def careers() -> dict[str, dict]:
    """playerID -> career totals (engine.STATS)."""
    c: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    years: dict[str, set] = defaultdict(set)
    for r in _rows("Appearances"):
        c[r["playerID"]]["G"] += _i(r["G_all"])
        years[r["playerID"]].add(_i(r["yearID"]))
    for r in _rows("Batting"):
        d = c[r["playerID"]]
        for col, key in (("AB", "AB"), ("R", "R"), ("H", "H"), ("2B", "doubles"), ("X2B", "doubles"),
                         ("3B", "triples"), ("X3B", "triples"), ("HR", "HR"), ("RBI", "RBI"), ("SB", "SB"),
                         ("BB", "BB"), ("SO", "SO")):
            if col in r:
                d[key] += _i(r[col])
    for r in _rows("Pitching"):
        d = c[r["playerID"]]
        d["W"] += _i(r["W"])
        d["L"] += _i(r["L"])
        d["GS"] += _i(r["GS"])
        d["SV"] += _i(r["SV"])
        d["IP"] += _i(r["IPouts"]) / 3
        d["ER"] += _i(r["ER"])
        d["K"] += _i(r["SO"])
    allstar: dict[str, set] = defaultdict(set)
    for r in _rows("AllstarFull"):
        if r["lgID"] in ("AL", "NL"):
            allstar[r["playerID"]].add(r["yearID"])
    for pid, ys in allstar.items():
        c[pid]["AS"] = len(ys)
    for r in _rows("HallOfFame"):
        if r["category"] == "Player" and r["inducted"] == "Y":
            c[r["playerID"]]["HOF"] = 1
    for r in _rows("AwardsPlayers"):
        if r["awardID"] == "Most Valuable Player":
            c[r["playerID"]]["MVP"] += 1
        elif r["awardID"] == "Cy Young Award":
            c[r["playerID"]]["CY"] += 1
    for pid, ys in years.items():
        c[pid]["seasons"] = len(ys)
        c[pid]["debut"] = min(ys)
    return c


# -------------------------------------------------------------------------- population

class Population:
    """Reads one year of the ISIMIP grid for a lat/lon box (people per 5' cell, NaN = sea)."""

    def __init__(self, raw: Path):
        import h5py
        import numpy as np
        self.files = [h5py.File(raw / "isimip" / f, "r") for f in POP_FILES]
        self.lat = self.files[0]["lat"][:]
        self.lon = self.files[0]["lon"][:]
        self.index = {}
        for k, f in enumerate(self.files):
            for t, v in enumerate(f["time"][:]):
                self.index[1850 + int(round(v))] = (k, t)
        self.np = np

    def box(self, year: int, la1: float, la2: float, lo1: float, lo2: float):
        np = self.np
        k, t = self.index[year]
        rows = np.where((self.lat >= la1) & (self.lat <= la2))[0]
        cols = np.where((self.lon >= lo1) & (self.lon <= lo2))[0]
        a = self.files[k]["total-population"][t, rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].astype(float)
        a[a > 1e19] = np.nan
        return self.lat[rows[0]:rows[-1] + 1], self.lon[cols[0]:cols[-1] + 1], a


# the params the prebuilt circles depend on (changing one needs `ballmonitor fetch` again)
GRID_PARAMS = ("people", "cell_km", "pop_cell_km", "min_radius_km", "max_radius_km", "radius_step", "exact_iterations",
               "first_decade", "last_decade", "pop_first_year", "pop_last_year")


def pop_year(decade: int, p) -> int:
    return int(min(max(decade + 5, p.pop_first_year), p.pop_last_year))


def build_grids(raw: Path, data: Path, p, players: list[dict], log=print) -> dict:
    pop = Population(raw)
    frames = E.make_frames(p)
    margin = float(p.max_radius_km) / 111.0
    (data / "grid").mkdir(parents=True, exist_ok=True)
    decades = list(range(int(p.first_decade), int(p.last_decade) + 10, 10))
    counts = defaultdict(int)
    for r in players:
        counts[E.decade_for(r["born"], p)] += 1
    for d in decades:
        year = pop_year(d, p)
        for fr in frames:
            lat0, lon0, la1, la2, lo1, lo2 = (float(v) for v in getattr(p, f"frame_{fr.name}"))
            dlon = margin / max(math.cos(math.radians(max(abs(la1), abs(la2)) + margin)), 0.2)
            lat, lon, a = pop.box(year, la1 - margin, la2 + margin, max(-180, lo1 - dlon), min(180, lo2 + dlon))
            code, held = E.radius_grid(lat, lon, a, fr, p)
            (data / "grid" / f"{d}_{fr.name}.png").write_bytes(E.png_bytes(code))
            (data / "grid" / f"{d}_{fr.name}_people.png").write_bytes(E.png_bytes(held))
            # people per map cell, for drawn regions (log-encoded)
            pc = float(p.pop_cell_km)
            grid, _, gx0, gy0 = E._binned(lat, lon, a, fr, pc, int(math.ceil(float(p.max_radius_km) / pc)) + 2)
            cells = E.cell_population(grid, gx0, gy0, pc, fr)
            cells[code == E.OCEAN] = 0
            (data / "grid" / f"{d}_{fr.name}_pop.png").write_bytes(E.png_bytes(E.pop_encode(cells)))
        log(f"  {d}s: population {year}, {counts.get(d, 0)} players")
    meta = {"frames": [f.to_json() for f in frames], "decades": decades,
            "pop_year": {str(d): pop_year(d, p) for d in decades}, "players": {str(d): counts.get(d, 0) for d in decades},
            "people": int(p.people), "radius_unit_km": 0.1, "people_unit": E.PEOPLE_UNIT, "ocean": E.OCEAN, "none_within": E.NONE_WITHIN,
            "max_radius_km": float(p.max_radius_km),
            "built_with": {k: float(getattr(p, k)) for k in GRID_PARAMS}}
    (data / "grid" / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    return meta


# ----------------------------------------------------------------------------- borders

def read_shp(path: Path) -> list[list[list[tuple[float, float]]]]:
    """Polygons (shape type 5) from a .shp: [shape -> [ring -> [(lon, lat)]]]."""
    data = path.read_bytes()
    pos, out = 100, []
    while pos < len(data):
        _, length = struct.unpack(">ii", data[pos:pos + 8])
        rec = data[pos + 8:pos + 8 + 2 * length]
        pos += 8 + 2 * length
        if struct.unpack("<i", rec[:4])[0] != 5:
            continue
        nparts, npts = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts])) + [npts]
        pts = struct.unpack(f"<{2 * npts}d", rec[44 + 4 * nparts:44 + 4 * nparts + 16 * npts])
        out.append([[(pts[2 * k], pts[2 * k + 1]) for k in range(parts[q], parts[q + 1])] for q in range(nparts)])
    return out


def _simplify(line: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker in km."""
    if len(line) < 3:
        return line
    (x1, y1), (x2, y2) = line[0], line[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-9
    best, idx = -1.0, 0
    for k in range(1, len(line) - 1):
        x, y = line[k]
        d = abs(dy * (x - x1) - dx * (y - y1)) / norm if (dx or dy) else math.hypot(x - x1, y - y1)
        if d > best:
            best, idx = d, k
    if best <= tol:
        return [line[0], line[-1]]
    return _simplify(line[:idx + 1], tol)[:-1] + _simplify(line[idx:], tol)


def build_borders(raw: Path, data: Path, p) -> None:
    frames = E.make_frames(p)
    out = {}
    for fr in frames:
        lat0, lon0, la1, la2, lo1, lo2 = (float(v) for v in getattr(p, f"frame_{fr.name}"))
        layers = {}
        for layer, name in (("countries", NE_FILES[0]), ("states", NE_FILES[1])):
            paths = []
            for shape in read_shp(raw / "natural-earth" / f"{name}.shp"):
                for ring in shape:
                    if not any(la1 - 2 <= lat <= la2 + 2 and lo1 - 2 <= lon <= lo2 + 2 for lon, lat in ring):
                        continue
                    pts = [E.laea(lat, lon, fr.lat0, fr.lon0) for lon, lat in ring]
                    pts = _simplify(pts, fr.cell / 4)
                    if len(pts) >= 3:
                        paths.append([[round(x, 1), round(y, 1)] for x, y in pts])
            layers[layer] = paths
        out[fr.name] = layers
    (data / "borders.json").write_text(json.dumps(out, separators=(",", ":")))


# -------------------------------------------------------------------------------- main

PLAYER_COLS = ["playerID", "name", "born", "lat", "lon", "place", "place_pop"] + [k for k in E.STATS if k != "born"]


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    model_dir = Path(model_dir)
    data, raw = model_dir / "data", model_dir / "data" / "raw"
    p = registry.load_model(model_dir.name).params
    raw_inputs(raw, offline)
    geo, counts = geocode(LAHMAN / "People.csv", raw / "geonames")
    people = {r["playerID"]: r for r in _rows("People")}
    car = careers()
    placed, unplaced = [], []
    for g in geo:
        r = people[g["playerID"]]
        born = r["birthYear"]
        if g["status"] != "matched" or not born:
            unplaced.append({"playerID": g["playerID"], "name": f"{r['nameFirst']} {r['nameLast']}".strip(),
                             "born": born, "birthplace": ", ".join(x for x in (r["birthCity"], r["birthState"], r["birthCountry"]) if x),
                             "why": g["status"] if g["status"] != "matched" else "no_birth_year"})
            continue
        c = car.get(g["playerID"], {})
        row = {"playerID": g["playerID"], "name": f"{r['nameFirst']} {r['nameLast']}".strip(), "born": int(born),
               "lat": g["lat"], "lon": g["lon"], "place": g["place"], "place_pop": g["place_pop"]}
        for k in E.STATS:
            if k not in ("born",):
                v = c.get(k, 0)
                row[k] = round(v, 1) if isinstance(v, float) and v != int(v) else int(v)
        placed.append(row)
    with (data / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PLAYER_COLS)
        w.writeheader()
        w.writerows(placed)
    with (data / "unplaced.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["playerID", "name", "born", "birthplace", "why"])
        w.writeheader()
        w.writerows(unplaced)
    lines = [f"players placed {len(placed)}, left off {len(unplaced)} ({dict(counts)})"]
    meta = build_grids(raw, data, p, placed, log=lambda s: lines.append(s))
    build_borders(raw, data, p)
    meta["geocoding"] = counts
    meta["placed"] = len(placed)
    meta["unplaced"] = len(unplaced)
    (data / "grid" / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    return lines
