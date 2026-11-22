"""Where baseball players come from. See MODEL.md.

predict(): one place and one birth decade -> the map's value there (formula `value`), how many
big-leaguers per million were born within the place's circle (`people`, 10 million), its size, and who they
were. The public page's map (web/static/apps/birthplace_map.js) computes the same for every cell.
"""

from __future__ import annotations

import math
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.prediction import Table

from . import engine as E


class BaseballBirthplacesModel(BaseModel):
    def locate(self, lat: float, lon: float) -> tuple[dict, int, int]:
        """(frame, column, row) of the map cell containing a point (the first frame that has it)."""
        meta = E.grid_meta(self.dir / "data")
        for f in meta["frames"]:
            x, y = E.laea(lat, lon, f["lat0"], f["lon0"])
            i = math.floor((x - f["x0"]) / f["cell"])
            j = f["ny"] - 1 - math.floor((y - f["y0"]) / f["cell"])
            if 0 <= i < f["nx"] and 0 <= j < f["ny"]:
                return f, i, j
        raise ValueError(f"({lat}, {lon}) is outside every map frame")

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        if inputs.get("region"):
            return self._region(inputs)
        p = self.params
        data = self.dir / "data"
        lat, lon = float(inputs["lat"]), float(inputs["lon"])
        label = str(inputs.get("place") or f"{lat:.2f}, {lon:.2f}")
        decade = E.decade_for(inputs["decade"], p)
        meta = E.grid_meta(data)
        if decade not in meta["decades"]:
            raise ValueError(f"decade must be one of {meta['decades']}")
        f, i, j = self.locate(lat, lon)
        code = E.load_grid(data, decade, f["name"])
        c = code[j][i]
        year = meta["pop_year"][str(decade)]
        players = [r for r in E.load_players(data, p) if E.decade_for(r["born"], p) == decade]
        built = meta.get("built_with", {})
        stale = sorted(k for k, v in built.items() if float(getattr(p, k)) != float(v))
        steps = [f"{len(players)} big-leaguers born in the {decade}s are placed on the map (Lahman birthplaces matched to GeoNames).",
                 f"{label} lies in map cell ({i}, {j}) of the {f['label']} frame ({f['cell']:g} km cells, equal-area projection "
                 f"centred on {f['lat0']}, {f['lon0']})."]
        if stale:
            steps.append(f"The circles were built with {', '.join(f'{k} = {built[k]:g}' for k in stale)}; changing them "
                         "needs a rebuild of the grids (ballmonitor fetch baseball_birthplaces), so the prebuilt circles are used.")
        if c == E.OCEAN:
            raise ValueError(f"{label} is in a water cell of the map")
        if c == E.NONE_WITHIN:
            steps.append(f"No circle up to {p.max_radius_km:g} km around it held {int(p.people):,} people in {year}: no value.")
            return self.prediction(inputs={"place": label, "decade": f"{decade}s"},
                                   outcomes=[Outcome("Value", estimate=0.0, note="no circle of enough people")], steps=steps)
        r = c / 10
        steps.append(f"Smallest circle holding {int(p.people):,} people in {year} (ISIMIP/HYDE population grid): {r:.1f} km.")
        steps.append(f"Each player counts by the share of his birthplace disk inside the circle; disk radius "
                     f"{p.expr('spread')} (0 for towns).")
        try:
            E.check_names(p.expr("value"), meta["decades"])
        except ValueError as exc:
            raise ValueError(f"formula value: {exc}") from None
        others = sorted(E.decades_in(p.expr("value")) - {decade})
        everyone = E.load_players(data, p)
        by = {d: [r for r in everyone if E.decade_for(r["born"], p) == d] for d in {decade, *others}}
        grids = {d: (E.load_grid(data, d, f["name"]), E.load_people(data, d, f["name"])) for d in {decade, *others}}
        held = grids[decade][1][j][i] * E.people_unit(p.people)
        steps.append(f"People inside the stored circle: {held:,} (sums are scaled by {int(p.per_people):,} / {held:,} "
                     f"so they are exactly per {int(p.per_people):,} people).")
        if others:
            steps.append("The value formula also uses " + ", ".join(f"the {d}s (circle {grids[d][0][j][i] / 10:.1f} km)" for d in others)
                         + f", each in its own decade's {int(p.people):,}-person circle.")
        val = E.cell_values(by, grids, f, p, decade, cells=[(i, j)]).get((i, j))
        x0, y0 = f["x0"] + (i + 0.5) * f["cell"], f["y0"] + (f["ny"] - j - 0.5) * f["cell"]
        inside = []
        for q in players:
            if not E.safe(lambda **v: p.formula("include", **v), **{k: q[k] for k in E.STATS}):
                continue
            x, y = E.laea(q["lat"], q["lon"], f["lat0"], f["lon0"])
            w = E.overlap(math.hypot(x - x0, y - y0), r, q["spread"])
            if w > 0:
                inside.append((w, q))
        n = sum(w for w, _ in inside) * float(p.per_people) / held
        steps.append(f"Included players (formula include: {p.expr('include')}) per million people: {n:.2f}; "
                     f"value = {p.expr('value')} = {'none' if val is None else f'{val:.4g}'}.")
        inside.sort(key=lambda t: -t[1]["G"])
        rows = [[q["name"], str(int(q["born"])), q["place"].split(",")[0][:18], f"{w:.2f}", f"{int(q['G']):,}"]
                for w, q in inside[:15]]
        return self.prediction(
            inputs={"place": label, "lat, lon": f"{lat:.3f}, {lon:.3f}", "decade": f"{decade}s",
                    "population year": year},
            outcomes=[Outcome(f"Value ({p.expr('value')}) per {int(p.per_people):,} people", estimate=val if val is not None else 0.0,
                              note="" if val is not None else "not computable here"),
                      Outcome("Big-leaguers per million (this decade)", estimate=n, group="Circle"),
                      Outcome("Circle radius (km)", estimate=r, group="Circle")],
            steps=steps,
            tables=[Table(f"Players born in the circle (most games first, {min(15, len(inside))} of {len(inside)})",
                          ["Player", "Born", "Place", "Share", "G"], rows)] if rows else [],
            extras={"value": val, "players": n, "people_in_circle": held, "radius_km": r, "frame": f["name"], "cell": [i, j], "stale_grid": stale},
        )

    def _region(self, inputs: dict[str, Any]) -> Prediction:
        """A drawn area: `region` = [[lat, lon], ...] corners -> its big-leaguers and the value
        formula per million people, every decade and all decades together (engine.region_stats)."""
        p = self.params
        data = self.dir / "data"
        corners = [(float(a), float(b)) for a, b in inputs["region"]]
        if len(corners) < 3:
            raise ValueError("region needs at least 3 corners [lat, lon]")
        name = str(inputs.get("name") or "the area")
        f, _, _ = self.locate(*corners[0])
        poly = [E.laea(a, b, f["lat0"], f["lon0"]) for a, b in corners]
        meta = E.grid_meta(data)
        E.check_names(p.expr("value"), meta["decades"])
        everyone = E.load_players(data, p)
        by = {d: [r for r in everyone if E.decade_for(r["born"], p) == d] for d in meta["decades"]}
        pops = {d: E.load_pop(data, d, f["name"]) for d in meta["decades"]}
        res = E.region_stats(by, pops, f, poly, p)
        per = float(p.per_people)
        steps = [f"{name}: a {len(corners)}-corner area in the {f['label']} frame (equal-area projection centred on "
                 f"{f['lat0']}, {f['lon0']}).",
                 f"Population per decade: each {f['cell']:g} km map cell's people (ISIMIP/HYDE, the decade's middle year) "
                 f"times the share of its {E.CELL_SAMPLES}x{E.CELL_SAMPLES} sample points inside the area.",
                 f"Players: born in the decade, formula include ({p.expr('include')}), each counted by the share of his "
                 f"birthplace disk's sample points inside (radius {p.expr('spread')}).",
                 f"Values: formula value ({p.expr('value')}) on the sums per {int(per):,} people; all decades together divide "
                 "every decade's births by that decade's population (per million people per decade)."]
        rows = []
        for d, r in res["decades"].items():
            pm = r["players"] * per / r["people"] if r["people"] > 0 else None
            rows.append([f"{d}s", f"{r['people']:,.0f}", f"{r['players']:.1f}", "-" if pm is None else f"{pm:.2f}",
                         "-" if r["value"] is None else f"{r['value']:.4g}"])
        t = res["total"]
        pm_all = t["players"] * per / t["people"] if t["people"] > 0 else 0.0
        return self.prediction(
            inputs={"area": name, "corners": len(corners), "frame": f["label"]},
            outcomes=[Outcome(f"Value ({p.expr('value')}), all decades", estimate=t["value"] if t["value"] is not None else 0.0,
                              note="" if t["value"] is not None else "not computable"),
                      Outcome("Big-leaguers born there", estimate=t["players"], group="All decades"),
                      Outcome("Per million people per decade", estimate=pm_all, group="All decades")],
            steps=steps,
            tables=[Table(f"{name} by birth decade", ["Born in", "People", "Players", "Per million", "Value"], rows)],
            extras={"total": {k: t[k] for k in ("people", "players", "value")},
                    "decades": {d: {k: r[k] for k in ("people", "players", "value")} for d, r in res["decades"].items()}},
        )
