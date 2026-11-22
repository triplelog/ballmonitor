"""The birthplace maps' arithmetic. See MODEL.md.

Each map frame (the main map, Alaska, Hawaii) has its own Lambert azimuthal equal-area
projection (spherical, km), so distances inside a frame are close to true. For every 20 km
display cell and every birth decade, the smallest circle around the cell's centre that holds
`people` people (from the historical population grid) is found; the map shows a formula over the
career totals of the players born inside it. The browser app (web/static/apps/birthplace_map.js)
is a copy of `laea`, `cell_values` and the formula rules; tests/test_birthplace_map_app.py checks it.
"""

from __future__ import annotations

import csv
import json
import re
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

R_EARTH = 6371.0088  # km, mean radius (definitional)
NONE_WITHIN = 65535   # radius code: no circle up to max_radius_km holds enough people
OCEAN = 0             # radius code: not land (not drawn)
PEOPLE_UNIT = 50      # people grid units per million people in a circle (50 for 1 million, 500 for 10 million)


def people_unit(people: float) -> int:
    """The people grid's unit for circles of `people`: 1/20,000 of it (16-bit codes reach 3.3 x people)."""
    return max(1, round(PEOPLE_UNIT * float(people) / 1e6))
DECADE_NAME = re.compile(r"([A-Za-z]\w*?)_(\d{4})$")   # HR_1910: a number for another birth decade

# Career numbers each player carries; formulas use these names. (label, description)
STATS = {
    "G": "games played", "AB": "at-bats", "R": "runs", "H": "hits", "doubles": "doubles", "triples": "triples",
    "HR": "home runs", "RBI": "runs batted in", "SB": "stolen bases", "BB": "walks (batting)",
    "SO": "strikeouts (batting)", "W": "wins (pitching)", "L": "losses (pitching)", "GS": "games started (pitching)",
    "SV": "saves", "IP": "innings pitched", "ER": "earned runs allowed", "K": "strikeouts (pitching)",
    "AS": "All-Star selections", "HOF": "Hall of Famer (1 or 0)", "MVP": "MVP awards", "CY": "Cy Young awards",
    "seasons": "seasons played", "debut": "first season (year)", "born": "birth year",
}


# --------------------------------------------------------------------------- projection

def laea(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Spherical Lambert azimuthal equal-area, km. Same formula as the browser app."""
    phi, lam = math.radians(lat), math.radians(lon - lon0)
    phi0 = math.radians(lat0)
    c = 1 + math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam)
    k = math.sqrt(2 / max(c, 1e-12))
    return (R_EARTH * k * math.cos(phi) * math.sin(lam),
            R_EARTH * k * (math.cos(phi0) * math.sin(phi) - math.sin(phi0) * math.cos(phi) * math.cos(lam)))


def laea_np(lat, lon, lat0: float, lon0: float):
    import numpy as np
    phi, lam = np.radians(lat), np.radians(lon - lon0)
    phi0 = math.radians(lat0)
    c = 1 + math.sin(phi0) * np.sin(phi) + math.cos(phi0) * np.cos(phi) * np.cos(lam)
    k = np.sqrt(2 / np.maximum(c, 1e-12))
    return (R_EARTH * k * np.cos(phi) * np.sin(lam),
            R_EARTH * k * (math.cos(phi0) * np.sin(phi) - math.sin(phi0) * np.cos(phi) * np.cos(lam)))


@dataclass
class Frame:
    name: str
    label: str
    lat0: float
    lon0: float
    x0: float   # display extent, km (cell edges)
    y0: float
    nx: int
    ny: int
    cell: float  # display cell size, km

    def center(self, i: int, j: int) -> tuple[float, float]:
        """Centre of display cell (column i, row j); row 0 is the top (north)."""
        return self.x0 + (i + 0.5) * self.cell, self.y0 + (self.ny - j - 0.5) * self.cell

    def to_json(self) -> dict:
        return {"name": self.name, "label": self.label, "lat0": self.lat0, "lon0": self.lon0, "x0": self.x0,
                "y0": self.y0, "nx": self.nx, "ny": self.ny, "cell": self.cell}


def make_frames(p) -> list[Frame]:
    """Frames from the params frame_<name> = [label?, lat0, lon0, lat_min, lat_max, lon_min, lon_max]:
    the display extent is the projected bounding box of that lat/lon box."""
    out = []
    for name, label in (("main", "Main"), ("alaska", "Alaska"), ("hawaii", "Hawaii")):
        lat0, lon0, la1, la2, lo1, lo2 = (float(v) for v in getattr(p, f"frame_{name}"))
        xs, ys = [], []
        for k in range(41):
            for lat, lon in ((la1 + (la2 - la1) * k / 40, lo1), (la1 + (la2 - la1) * k / 40, lo2),
                             (la1, lo1 + (lo2 - lo1) * k / 40), (la2, lo1 + (lo2 - lo1) * k / 40)):
                x, y = laea(lat, lon, lat0, lon0)
                xs.append(x)
                ys.append(y)
        cell = float(p.cell_km)
        x0 = math.floor(min(xs) / cell) * cell
        y0 = math.floor(min(ys) / cell) * cell
        nx = int(math.ceil((max(xs) - x0) / cell))
        ny = int(math.ceil((max(ys) - y0) / cell))
        out.append(Frame(name, {"main": "Main", "alaska": "Alaska", "hawaii": "Hawaii"}[name], lat0, lon0,
                         x0, y0, nx, ny, cell))
    return out


# ------------------------------------------------------------------------ circle sizes

def ladder(p) -> list[float]:
    """Radii tried, km: geometric from min_radius_km to max_radius_km."""
    r, out = float(p.min_radius_km), []
    while r < float(p.max_radius_km):
        out.append(r)
        r *= 1 + float(p.radius_step)
    return out + [float(p.max_radius_km)]


def disk_kernel(radius_km: float, cell_km: float, sub: int = 5):
    """Fraction of each grid cell inside a disk of radius_km (sub x sub samples per cell)."""
    import numpy as np
    n = int(math.ceil(radius_km / cell_km)) + 1
    offs = (np.arange(sub) + 0.5) / sub - 0.5
    ax = np.arange(-n, n + 1)
    gx = (ax[:, None] + offs[None, :]).reshape(-1) * cell_km
    d2 = gx[:, None] ** 2 + gx[None, :] ** 2
    inside = (d2 <= radius_km ** 2).reshape(2 * n + 1, sub, 2 * n + 1, sub)
    return inside.mean(axis=(1, 3))


def _binned(pop_lat, pop_lon, pop, frame: Frame, pc: float, margin: int):
    """People per `pc` km cell in the frame's projection. Pop-cell centres are placed so every map
    cell's centre is a pop-cell centre. Returns (grid[row, col] with row 0 south, land mask,
    x of column 0's centre, y of row 0's centre)."""
    import numpy as np
    off = (frame.cell / 2) % pc
    gx0 = frame.x0 + off - margin * pc
    gy0 = frame.y0 + off - margin * pc
    gnx = int(math.ceil(frame.nx * frame.cell / pc)) + 2 * margin + 1
    gny = int(math.ceil(frame.ny * frame.cell / pc)) + 2 * margin + 1
    lat2, lon2 = np.meshgrid(pop_lat, pop_lon, indexing="ij")
    x, y = laea_np(lat2, lon2, frame.lat0, frame.lon0)
    ix = np.floor((x - gx0) / pc + 0.5).astype(int)
    iy = np.floor((y - gy0) / pc + 0.5).astype(int)
    ok = (ix >= 0) & (ix < gnx) & (iy >= 0) & (iy < gny) & np.isfinite(pop)
    grid = np.zeros((gny, gnx))
    np.add.at(grid, (iy[ok], ix[ok]), pop[ok])
    land = np.zeros((gny, gnx), bool)
    land[iy[ok], ix[ok]] = True
    return grid, land, gx0, gy0


def people_within(prefix, grid, rows, cols, rho, n_max: int):
    """People inside circles of radius rho (in pop cells) centred on pop cells (rows, cols):
    each row of cells is cut at the circle's chord through the row's centre line, partial end
    cells counted by the fraction covered (midpoint rule in y). Vectorised over the circles.
    prefix[row, k] = people in columns < k of that row."""
    import numpy as np
    total = np.zeros(len(rows))
    gnx = grid.shape[1]
    for dy in range(-n_max, n_max + 1):
        c = np.sqrt(np.maximum(rho * rho - dy * dy, 0.0))
        live = c > 0
        if not live.any():
            continue
        rr = rows + dy
        live &= (rr >= 0) & (rr < grid.shape[0])   # rows past the grid's edge hold no one
        rr = np.clip(rr, 0, grid.shape[0] - 1)

        def cum(t):   # people from the row's left edge to continuous column coordinate t (centres at k)
            t = np.clip(t + 0.5, 0, gnx)
            k = np.minimum(np.floor(t).astype(int), gnx - 1)
            return prefix[rr, k] + (t - k) * grid[rr, k]
        total += np.where(live, cum(cols + c) - cum(cols - c), 0.0)
    return total


def radius_grid(pop_lat, pop_lon, pop, frame: Frame, p):
    """(radius code, people code) for every display cell of `frame`. Radius in 0.1 km (OCEAN,
    NONE_WITHIN): the smallest circle holding `people` people. People: the population inside that
    stored circle in units of PEOPLE_UNIT, which the map divides by, so values are exactly per
    `people` even where a dense population cell makes the count jump past `people`.

    pop: people per population-grid cell (NaN = sea) at pop_lat (rows) x pop_lon (cols). It is
    binned into a `pop_cell_km` grid in the frame's projection (margin max_radius_km), convolved
    with a disk for each radius in ladder() to find the two radii around `people`, and then the
    radius is narrowed by bisection on people_within() until the circle holds `people`."""
    import numpy as np
    from scipy.signal import fftconvolve
    pc = float(p.pop_cell_km)
    margin = int(math.ceil(float(p.max_radius_km) / pc)) + 2
    grid, landgrid, gx0, gy0 = _binned(pop_lat, pop_lon, pop, frame, pc, margin)
    # pop-grid indices of every display cell's centre
    cols = np.rint((frame.x0 + (np.arange(frame.nx) + 0.5) * frame.cell - gx0) / pc).astype(int)
    rows = np.rint((frame.y0 + (frame.ny - np.arange(frame.ny) - 0.5) * frame.cell - gy0) / pc).astype(int)
    R2, C2 = np.meshgrid(rows, cols, indexing="ij")
    radii = ladder(p)
    people = float(p.people)
    lo = np.zeros((frame.ny, frame.nx))
    hi = np.full((frame.ny, frame.nx), np.nan)
    for r in radii:
        s = fftconvolve(grid, disk_kernel(r, pc), mode="same")[R2, C2]
        new = np.isnan(hi) & (s >= people)
        hi[new] = r
        lo[np.isnan(hi)] = r
    out = np.full((frame.ny, frame.nx), NONE_WITHIN, dtype=np.uint16)
    people_out = np.zeros((frame.ny, frame.nx), dtype=np.uint16)
    found = ~np.isnan(hi)
    if found.any():
        prefix = np.zeros((grid.shape[0], grid.shape[1] + 1))
        prefix[:, 1:] = np.cumsum(grid, axis=1)
        a, b = lo[found], hi[found]
        rr, cc = R2[found], C2[found]
        # the ladder used the disk convolution; make sure the exact count brackets `people` too
        for _ in range(12):
            n_max = int(math.ceil(float(np.max(b)) / pc)) + 1
            short = people_within(prefix, grid, rr, cc, b / pc, n_max) < people
            if not short.any():
                break
            a = np.where(short, b, a)
            b = np.where(short, np.minimum(b * (1 + float(p.radius_step)), float(p.max_radius_km)), b)
        over = people_within(prefix, grid, rr, cc, a / pc, int(math.ceil(float(np.max(a)) / pc)) + 1) >= people
        a = np.where(over, 0.0, a)
        n_max = int(math.ceil(float(np.max(b)) / pc)) + 1
        for _ in range(int(p.exact_iterations)):
            mid = (a + b) / 2
            enough = people_within(prefix, grid, rr, cc, mid / pc, n_max) >= people
            b = np.where(enough, mid, b)
            a = np.where(enough, a, mid)
        n_max = int(math.ceil(float(np.max(b)) / pc)) + 1
        reached = people_within(prefix, grid, rr, cc, b / pc, n_max) >= people * (1 - 1e-6)
        stored = np.where(reached, np.maximum(1, np.round(b * 10)), NONE_WITHIN).astype(np.uint16)
        out[found] = stored
        # the people inside each circle as stored (rounded to 0.1 km): the exact per-capita divisor
        ok = stored != NONE_WITHIN
        if ok.any():
            held = people_within(prefix, grid, rr[ok], cc[ok], stored[ok] / 10 / pc, n_max)
            pf = people_out[found]
            pf[ok] = np.clip(np.round(held / people_unit(people)), 1, 65535)
            people_out[found] = pf
    # land: any pop cell whose centre lies in the display cell
    k = int(round(frame.cell / pc))
    lg = np.zeros((frame.ny, frame.nx), bool)
    for da in range(-(k // 2), k - k // 2):
        for db in range(-(k // 2), k - k // 2):
            lg |= landgrid[np.clip(R2 + da, 0, grid.shape[0] - 1), np.clip(C2 + db, 0, grid.shape[1] - 1)]
    out[~lg] = OCEAN
    people_out[(out == OCEAN) | (out == NONE_WITHIN)] = 0
    return out, people_out


def circle_people(pop_lat, pop_lon, pop, frame: Frame, p, code, cells):
    """People inside the stored circles of `cells` [(i, j)] (people_within, for checks)."""
    import numpy as np
    pc = float(p.pop_cell_km)
    margin = int(math.ceil(float(p.max_radius_km) / pc)) + 2
    grid, _, gx0, gy0 = _binned(pop_lat, pop_lon, pop, frame, pc, margin)
    prefix = np.zeros((grid.shape[0], grid.shape[1] + 1))
    prefix[:, 1:] = np.cumsum(grid, axis=1)
    ii = np.array([c[0] for c in cells])
    jj = np.array([c[1] for c in cells])
    cols = np.rint((frame.x0 + (ii + 0.5) * frame.cell - gx0) / pc).astype(int)
    rows = np.rint((frame.y0 + (frame.ny - jj - 0.5) * frame.cell - gy0) / pc).astype(int)
    rad = np.array([code[j][i] / 10 for i, j in cells])
    return people_within(prefix, grid, rows, cols, rad / pc, int(math.ceil(rad.max() / pc)) + 1)


# ------------------------------------------------------------------------------- PNG

def png_bytes(code) -> bytes:
    """uint16 grid -> RGB PNG (R = high byte, G = low byte, B = 0), filter 0, so the browser
    reads exact values from a canvas."""
    import numpy as np
    h, w = code.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[..., 0] = code >> 8
    rgb[..., 1] = code & 255
    raw = b"".join(b"\x00" + rgb[j].tobytes() for j in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def read_png(data: bytes) -> list[list[int]]:
    """Inverse of png_bytes (our own files only: 8-bit RGB, filter 0)."""
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t = data[pos + 4:pos + 8]
        d = data[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            w, h = struct.unpack(">II", d[:8])
        elif t == b"IDAT":
            idat += d
        pos += 12 + n
    raw = zlib.decompress(idat)
    out, stride = [], 1 + 3 * w
    for j in range(h):
        row = raw[j * stride + 1:(j + 1) * stride]
        out.append([row[3 * i] * 256 + row[3 * i + 1] for i in range(w)])
    return out


# ---------------------------------------------------------------------------- players

def decade_of(year) -> int | None:
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    return y - y % 10


def decade_for(born, p) -> int | None:
    """A player's map decade: his birth decade, those born before first_decade in the first one."""
    d = decade_of(born)
    if d is None:
        return None
    return min(max(d, int(p.first_decade)), int(p.last_decade))


def count_grid(players: list[dict], code, frame: dict, people=None, per: float = 1.0, unit: int = PEOPLE_UNIT):
    """How many of `players` were born within each cell's circle (numpy; NaN where not drawn);
    with the people grid, per `per` people (count x per / population in the circle)."""
    import numpy as np
    from scipy.spatial import cKDTree
    code = np.asarray(code)
    out = np.full(code.shape, np.nan)
    if not players:
        return out
    pts = np.array([laea(r["lat"], r["lon"], frame["lat0"], frame["lon0"]) for r in players])
    spread = np.array([r.get("spread", 0.0) for r in players])
    tree = cKDTree(pts)
    jj, ii = np.nonzero((code != OCEAN) & (code != NONE_WITHIN))
    cx = frame["x0"] + (ii + 0.5) * frame["cell"]
    cy = frame["y0"] + (frame["ny"] - jj - 0.5) * frame["cell"]
    rad = code[jj, ii] / 10
    near = tree.query_ball_point(np.c_[cx, cy], r=rad + spread.max())
    for q, idx in enumerate(near):
        out[jj[q], ii[q]] = sum(overlap(math.hypot(pts[k, 0] - cx[q], pts[k, 1] - cy[q]), rad[q], spread[k]) for k in idx)
    if people is not None:
        pg = np.asarray(people, dtype=float) * unit
        out = np.where(pg > 0, out * per / np.maximum(pg, 1), np.nan)
    return out


def load_players(data_dir: Path, p=None) -> list[dict]:
    """players.csv rows with numbers; with params, each gets `spread` (km, formula `spread`)."""
    with (data_dir / "players.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
        r["place_pop"] = float(r.get("place_pop") or 0)
        for k in STATS:
            r[k] = float(r[k] or 0)
        if p is not None:
            r["spread"] = round(float(p.formula("spread", place_pop=r["place_pop"])), 2)
    return rows


def _segment(r: float, h: float) -> float:
    """Area of the part of a circle of radius r beyond a chord at distance h from its centre."""
    h = max(-r, min(r, h))
    return r * r * math.acos(h / r) - h * math.sqrt(max(0.0, (r - h) * (r + h)))


def overlap(d: float, R: float, s: float) -> float:
    """Share of a player's birthplace disk (radius s, centre d km away) inside a circle of radius R.
    A disk under 10 m is a point: 1 if d <= R else 0. The lens area is two circular segments (stable
    when s is tiny next to R). Same formula as the browser app."""
    if s < 0.01:
        return 1.0 if d <= R else 0.0
    if d >= R + s:
        return 0.0
    if d <= R - s:
        return 1.0
    if d <= s - R:
        return (R * R) / (s * s)
    h = (d * d + R * R - s * s) / (2 * d)   # from the circle's centre to the chord
    return min(1.0, max(0.0, (_segment(R, h) + _segment(s, d - h)) / (math.pi * s * s)))


def load_pop(data_dir: Path, decade: int, frame: str) -> list[list[int]]:
    """People per map cell, log-encoded (pop_decode)."""
    return read_png((data_dir / "grid" / f"{decade}_{frame}_pop.png").read_bytes())


def load_people(data_dir: Path, decade: int, frame: str) -> list[list[int]]:
    return read_png((data_dir / "grid" / f"{decade}_{frame}_people.png").read_bytes())


def load_grid(data_dir: Path, decade: int, frame: str) -> list[list[int]]:
    return read_png((data_dir / "grid" / f"{decade}_{frame}.png").read_bytes())


def grid_meta(data_dir: Path) -> dict:
    return json.loads((data_dir / "grid" / "meta.json").read_text())


def safe(fn, **kw):
    """A formula's value, or None when it can't be computed (e.g. 0/0 in a cell with no players)."""
    try:
        v = fn(**kw)
    except (ZeroDivisionError, ValueError, OverflowError, TypeError):   # TypeError: a complex power
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def decades_in(expr: str) -> set[int]:
    """Birth decades a value formula names with a suffix (HR_1910 -> 1910)."""
    import ast
    return {int(m.group(2)) for n in ast.walk(ast.parse(expr.strip(), mode="eval"))
            if isinstance(n, ast.Name) and (m := DECADE_NAME.match(n.id))}


def check_names(expr: str, decades: list[int]) -> None:
    """Every suffixed name must be a known number and a mapped decade (ValueError otherwise)."""
    import ast
    for n in ast.walk(ast.parse(expr.strip(), mode="eval")):
        m = isinstance(n, ast.Name) and DECADE_NAME.match(n.id)
        if m:
            if m.group(1) not in STATS and m.group(1) != "players":
                raise ValueError(f"unknown name {m.group(1)!r} in {n.id!r}")
            if int(m.group(2)) not in decades:
                raise ValueError(f"no decade {m.group(2)} in {n.id!r}; decades: {decades[0]}-{decades[-1]} by 10")


def cell_sums(players: list[dict], code, people, frame: dict, p, cells) -> dict:
    """{(i, j): (players, {stat: sum})} per `per_people` people for one decade: the included
    players (formula `include`) born within each cell's circle, each counted by the share of his
    birthplace disk (radius `spread`) inside it, scaled by per_people / (population in the circle).
    Cells with no circle are left out."""
    pts = []
    for r in players:
        if safe(lambda **v: p.formula("include", **v), **{k: r[k] for k in STATS}):
            x, y = laea(r["lat"], r["lon"], frame["lat0"], frame["lon0"])
            pts.append((x, y, r.get("spread", 0.0), r))
    out = {}
    for i, j in cells:
        c = code[j][i]
        if c in (OCEAN, NONE_WITHIN):
            continue
        rad = c / 10
        scale = float(p.per_people) / (people[j][i] * people_unit(p.people)) if people is not None else 1.0
        cx = frame["x0"] + (i + 0.5) * frame["cell"]
        cy = frame["y0"] + (frame["ny"] - j - 0.5) * frame["cell"]
        sums = {k: 0.0 for k in STATS}
        n = 0.0
        for x, y, s, r in pts:
            w = overlap(math.hypot(x - cx, y - cy), rad, s)
            if w > 0:
                n += w
                for k in STATS:
                    sums[k] += w * r[k]
        out[(i, j)] = (n * scale, {k: v * scale for k, v in sums.items()})
    return out


def cell_values(by_decade: dict, grids: dict, frame: dict, p, decade: int, cells=None) -> dict:
    """Value of formula `value` for each display cell (or the given [(i, j)] cells) when the map
    shows `decade`. by_decade: {decade: players}; grids: {decade: (radius code, people code)}.
    Plain names (HR, players) are that decade's sums; suffixed names (HR_1910) another decade's,
    each in its own decade's million-person circle. A cell missing a circle in any decade the
    formula uses has no value. The browser app computes the same. Returns {(i, j): value or None}."""
    expr = p.expr("value")
    check_names(expr, sorted(grids))
    need = sorted({decade} | decades_in(expr))
    code0 = grids[decade][0]
    todo = cells if cells is not None else [(i, j) for j in range(len(code0)) for i in range(len(code0[0]))]
    sums = {d: cell_sums(by_decade.get(d, []), grids[d][0], grids[d][1], frame, p, todo) for d in need}
    out = {}
    for cell in todo:
        if cell not in sums[decade]:
            continue
        if any(cell not in sums[d] for d in need):
            out[cell] = None
            continue
        env = {}
        for d in need:
            n, st = sums[d][cell]
            env.update({f"{k}_{d}": v for k, v in st.items()})
            env[f"players_{d}"] = n
        n, st = sums[decade][cell]
        env.update(st)
        env["players"] = n
        out[cell] = safe(lambda **v: p.formula("value", **v), **env)
    return out


# ------------------------------------------------------------------------------- regions
# A visitor's drawn region: a polygon in one frame's projected km. Its population per decade comes
# from the people per map cell (grid/<decade>_<frame>_pop.png, log-encoded), each cell counted by
# the share of its CELL_SAMPLES x CELL_SAMPLES points inside the polygon; each player by the share
# of his birthplace disk's DISK_SAMPLES points inside it. The browser app does the same.

POP_LOG = 4000.0      # pop code = round(log1p(people) * POP_LOG): 0.025% steps up to about 13 million
CELL_SAMPLES = 4


def pop_encode(people):
    import numpy as np
    return np.clip(np.round(np.log1p(np.maximum(people, 0)) * POP_LOG), 0, 65535).astype(np.uint16)


def pop_decode(code: int) -> float:
    return math.expm1(code / POP_LOG)


def cell_population(grid, gx0: float, gy0: float, pc: float, frame: Frame):
    """People per map cell from the binned pop grid (pop-cell centres on map-cell centres and
    edges when cell = 2 x pop cell): tent weights share an edge cell between its two map cells."""
    import numpy as np
    from scipy.signal import convolve2d
    if abs(frame.cell - 2 * pc) > 1e-9:
        raise ValueError("cell_population needs cell_km = 2 x pop_cell_km")
    tent = np.array([[0.25, 0.5, 0.25], [0.5, 1.0, 0.5], [0.25, 0.5, 0.25]])
    s = convolve2d(grid, tent, mode="same")
    cols = np.rint((frame.x0 + (np.arange(frame.nx) + 0.5) * frame.cell - gx0) / pc).astype(int)
    rows = np.rint((frame.y0 + (frame.ny - np.arange(frame.ny) - 0.5) * frame.cell - gy0) / pc).astype(int)
    return s[np.ix_(rows, cols)]


def disk_points(s: float) -> list[tuple[float, float]]:
    """19 sample points spread evenly over a disk of radius s (centre + rings of 6 and 12);
    one point when s < 0.01 km. Same points as the browser app."""
    if s < 0.01:
        return [(0.0, 0.0)]
    pts = [(0.0, 0.0)]
    for n, rr in ((6, 0.5), (12, 0.866)):
        for k in range(n):
            a = 2 * math.pi * k / n
            pts.append((s * rr * math.cos(a), s * rr * math.sin(a)))
    return pts


def inside(px, py, poly) -> "np.ndarray":
    """Point-in-polygon (even-odd rule) for arrays of points; poly = [(x, y), ...] in km."""
    import numpy as np
    px, py = np.asarray(px, float), np.asarray(py, float)
    res = np.zeros(px.shape, bool)
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if y1 == y2:
            continue
        cross = (y1 > py) != (y2 > py)
        xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
        res ^= cross & (px < xint)
    return res


def region_population(pop_code, frame: dict, poly) -> float:
    """People in the polygon for one decade: each map cell's people times the share of its sample
    points inside."""
    import numpy as np
    pc = np.asarray(pop_code)
    xs = [x for x, _ in poly]
    ys = [y for _, y in poly]
    i0 = max(0, int(math.floor((min(xs) - frame["x0"]) / frame["cell"])))
    i1 = min(frame["nx"] - 1, int(math.floor((max(xs) - frame["x0"]) / frame["cell"])))
    j0 = max(0, frame["ny"] - 1 - int(math.floor((max(ys) - frame["y0"]) / frame["cell"])))
    j1 = min(frame["ny"] - 1, frame["ny"] - 1 - int(math.floor((min(ys) - frame["y0"]) / frame["cell"])))
    if i1 < i0 or j1 < j0:
        return 0.0
    ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
    offs = (np.arange(CELL_SAMPLES) + 0.5) / CELL_SAMPLES
    share = np.zeros(ii.shape)
    for a in offs:
        for b in offs:
            x = frame["x0"] + (ii + a) * frame["cell"]
            y = frame["y0"] + (frame["ny"] - jj - b) * frame["cell"]
            share += inside(x, y, poly)
    share /= CELL_SAMPLES ** 2
    codes = pc[jj, ii]
    people = np.expm1(codes / POP_LOG)
    return float((people * share).sum())


def region_shares(players: list[dict], frame: dict, poly) -> list[float]:
    """Each player's share inside the polygon (his birthplace disk's sample points inside)."""
    import numpy as np
    out = []
    for r in players:
        x, y = laea(r["lat"], r["lon"], frame["lat0"], frame["lon0"])
        pts = disk_points(r.get("spread", 0.0))
        hit = inside([x + dx for dx, _ in pts], [y + dy for _, dy in pts], poly)
        out.append(float(np.count_nonzero(hit)) / len(pts))
    return out


def region_stats(by_decade: dict, pops: dict, frame: dict, poly, p) -> dict:
    """For a polygon: per decade {people, players, sums, value} and the all-decade totals.
    by_decade: {decade: players}; pops: {decade: pop code grid}. Values are formula `value` on the
    sums scaled per `people` people (all decades: per `people` people per decade, i.e. divided by
    the sum of each decade's population). Suffixed names (HR_1910) are that decade's scaled sums."""
    decades = sorted(pops)
    per = float(p.per_people)
    rows = {}
    for d in decades:
        players = [r for r in by_decade.get(d, [])
                   if safe(lambda **v: p.formula("include", **v), **{k: r[k] for k in STATS})]
        shares = region_shares(players, frame, poly)
        sums = {k: sum(w * r[k] for w, r in zip(shares, players)) for k in STATS}
        rows[d] = {"people": region_population(pops[d], frame, poly), "players": sum(shares), "sums": sums,
                   "names": [(w, r) for w, r in zip(shares, players) if w > 0]}

    def scaled(row):
        f = per / row["people"] if row["people"] > 0 else None
        if f is None:
            return None
        return {"players": row["players"] * f, **{k: v * f for k, v in row["sums"].items()}}
    sc = {d: scaled(rows[d]) for d in decades}
    suffixed = {}
    for d in decades:
        if sc[d] is not None:
            suffixed.update({f"{k}_{d}": v for k, v in sc[d].items()})
    for d in decades:
        env = {**suffixed, **sc[d]} if sc[d] is not None else None
        rows[d]["value"] = safe(lambda **v: p.formula("value", **v), **env) if env else None
    total_people = sum(r["people"] for r in rows.values())
    total = {"people": total_people, "players": sum(r["players"] for r in rows.values()),
             "sums": {k: sum(r["sums"][k] for r in rows.values()) for k in STATS}}
    st = scaled(total)
    total["value"] = safe(lambda **v: p.formula("value", **v), **{**suffixed, **st}) if st else None
    return {"decades": rows, "total": total}
