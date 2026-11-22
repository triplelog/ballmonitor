"""Public page (/baseball_birthplaces/): maps of where big-leaguers were born, per million people,
one birth decade at a time, with the visitor's own formula and colours (web/static/apps/
birthplace_map.js computes the map in the browser from the files below), and a pre-built table of
the place with the most big-leaguers per million in each decade.

files(model) ships, per decade, the circle sizes (grid/<decade>_<frame>.png, built by fetch.py)
and the players born then (players/<decade>.json), plus the map outlines (borders.json); the page
loads one decade at a time.
"""

from __future__ import annotations

import json
from collections import Counter

from ballmonitor.core import views as V

from . import engine as E

PRESETS = [
    ("Big-leaguers", "1", "players"),
    ("Regulars (500+ games or 150+ starts)", "G >= 500 or GS >= 150", "players"),
    ("Home runs", "1", "HR"),
    ("Hits", "1", "H"),
    ("Stolen bases", "1", "SB"),
    ("Pitching wins", "1", "W"),
    ("Strikeouts by pitchers", "1", "K"),
    ("All-Star selections", "1", "AS"),
    ("Hall of Famers", "1", "HOF"),
    ("MVP awards", "1", "MVP"),
    ("Batting average of local hitters (1,000+ at-bats)", "AB >= 1000", "H / AB"),
    ("Seasons per big-leaguer", "1", "seasons / players"),
    ("Big-leaguers, 1980s vs 1910s (ratio)", "1", "players_1980 / players_1910"),
    ("Home runs, 1990s minus 1920s", "1", "HR_1990 - HR_1920"),
]


def millions(n) -> str:
    """10000000 -> "10 million", 1000000 -> "a million"."""
    m = float(n) / 1e6
    return "a million" if m == 1 else f"{m:g} million" if m >= 1 else f"{int(n):,}"


def _by_decade(model) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in E.load_players(model.dir / "data", model.params):
        d = E.decade_for(r["born"], model.params)
        if d is not None:
            out.setdefault(d, []).append(r)
    return out


def files(model) -> dict[str, bytes]:
    data = model.dir / "data"
    meta = E.grid_meta(data)
    out = {"borders.json": (data / "borders.json").read_bytes()}
    by = _by_decade(model)
    for d in meta["decades"]:
        for f in meta["frames"]:
            out[f"grid/{d}_{f['name']}.png"] = (data / "grid" / f"{d}_{f['name']}.png").read_bytes()
            out[f"grid/{d}_{f['name']}_people.png"] = (data / "grid" / f"{d}_{f['name']}_people.png").read_bytes()
            out[f"grid/{d}_{f['name']}_pop.png"] = (data / "grid" / f"{d}_{f['name']}_pop.png").read_bytes()
        rows = by.get(d, [])
        cols = {"name": [r["name"] for r in rows], "place": [r["place"] for r in rows],
                "lat": [r["lat"] for r in rows], "lon": [r["lon"] for r in rows], "spread": [r["spread"] for r in rows]}
        for k in E.STATS:
            cols[k] = [int(r[k]) if float(r[k]).is_integer() else round(r[k], 1) for r in rows]
        out[f"players/{d}.json"] = json.dumps(cols, separators=(",", ":")).encode()
    return out


def _top_places(model, meta, by) -> list[dict]:
    """Per decade, the map cell with the most big-leaguers per million people, named by the most
    common birthplace in its circle."""
    rows = []
    for d in meta["decades"]:
        players = by.get(d, [])
        best = None
        for f in meta["frames"]:
            code = E.load_grid(model.dir / "data", d, f["name"])
            counts = E.count_grid(players, code, f, E.load_people(model.dir / "data", d, f["name"]),
                                  float(model.params.per_people), E.people_unit(model.params.people))
            import numpy as np
            if np.isnan(counts).all():
                continue
            j, i = np.unravel_index(np.nanargmax(counts), counts.shape)
            if best is None or counts[j, i] > best[0]:
                best = (float(counts[j, i]), f, i, j, code[j][i] / 10)
        if not best:
            continue
        n, f, i, j, r = best
        cx, cy = f["x0"] + (i + 0.5) * f["cell"], f["y0"] + (f["ny"] - j - 0.5) * f["cell"]
        near: Counter = Counter()
        for q in players:
            x, y = E.laea(q["lat"], q["lon"], f["lat0"], f["lon0"])
            near[q["place"].split(",")[0]] += E.overlap(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5, r, q["spread"])
        place = near.most_common(1)[0][0] if near else "?"
        rows.append({"decade": f"{d}s", "place": place, "per_million": n, "radius": round(r),
                     "year": str(meta["pop_year"][str(d)]), "players": len(players)})
    return rows


def page(model) -> dict:
    p = model.params
    data_dir = model.dir / "data"
    meta = E.grid_meta(data_dir)
    by = _by_decade(model)
    top = _top_places(model, meta, by)
    decades = meta["decades"]
    circle = millions(p.people)
    default = decades[-2] if len(decades) > 1 else decades[-1]   # the last full decade
    app = V.app(
        "map", "Big-leaguers per million people, by birthplace", "birthplace_map",
        {"files": "/data/files/baseball_birthplaces/", "frames": meta["frames"], "decades": decades,
         "people": int(p.per_people), "people_unit": E.people_unit(p.people), "circle_people": int(p.people),
         "circle_label": circle,
         "pop_year": {int(k): v for k, v in meta["pop_year"].items()}, "players": meta["players"],
         "max_radius_km": meta["max_radius_km"], "default_decade": default,
         "include": p.expr("include"), "value": p.expr("value"), "palette": p.site_colors,
         "stats": E.STATS, "statNames": list(E.STATS),
         "presets": [{"label": a, "include": b, "value": c} for a, b, c in PRESETS]},
        subtitle=f"Every spot on the map gets the smallest circle around it holding {circle} people at the time; "
                 "the colour is how many big-leaguers were born in that circle in the decade you pick, per million people. Pick another "
                 "map, write your own formula, or draw your own areas on the map to compare them decade by decade.",
        note=f"Blank land: fewer than {circle} people within "
             f"{int(meta['max_radius_km']):,} km at the time (Hawaii always; Alaska and the far North for most decades).")
    table = V.table(
        "top", "The biggest hotbed of each decade",
        [V.col("decade", "Born in"), V.col("place", "Around"), V.col("per_million", "Big-leaguers per million", "number", decimals=1, bar=True),
         V.col("radius", "Circle (km)", "int"), V.col("year", "Population of"), V.col("players", "Big-leaguers born", "int")],
        top, subtitle=f"The spot whose {circle}-person circle produced the most big-leaguers per million people, named after the most common birthplace in it.")
    hot = top[-2] if len(top) > 1 else top[-1]
    headline = (f"Born in the {hot['decade']}: around {hot['place']}, {hot['per_million']:.0f} big-leaguers per million people, "
                "more than anywhere else on the map")
    return V.page(
        title="Where baseball players come from", sport="Baseball",
        summary="Maps of where big-leaguers were born, per million people, decade by decade since the 1840s.",
        how="Each player is placed at his birthplace from the Lahman database. For every spot on the map, the smallest circle "
            f"around it that held {circle} people in the decade (from historical population estimates) is found, and the map "
            "adds up the careers of the players born inside it, so every number is per million people. You can change what is "
            "added up and how it is coloured.",
        updated=f"Careers through {int(max(r['debut'] + r['seasons'] - 1 for rs in by.values() for r in rs))}; population estimates 1850-2021",
        headline=headline, fill={"placed": f"{meta.get('placed', 0):,}"},
        views=[app, V.clean(table)])
