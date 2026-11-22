"""Open WAR. See MODEL.md.

predict(): one player (Lahman playerID) -> career Open WAR and every season, computed from the
Lahman CSVs with the current parameters (so --set changes the answer), batting and pitching parts.
"""

from __future__ import annotations

from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.prediction import Table

from . import engine as E

_CACHE: dict = {}


class OpenWarModel(BaseModel):
    def seasons(self) -> list[dict]:
        """Every player-season with the current parameters (cached per parameter set)."""
        key = tuple(sorted((k, str(s.value)) for k, s in self.params.specs.items())) + tuple(
            sorted((k, f.expr) for k, f in self.params.formulas.items()))
        if key not in _CACHE:
            _CACHE.clear()
            _CACHE[key] = E.compute(self.params)
        return _CACHE[key]

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        pid = str(inputs["player"])
        rows = [r for r in self.seasons() if r["playerID"] == pid]
        if not rows:
            raise ValueError(f"no seasons for player {pid!r} (a Lahman playerID, e.g. ruthba01)")
        p = self.params
        total = sum(r["WAR"] for r in rows)
        bat = sum(r["bWAR"] for r in rows)
        pit = sum(r["pWAR"] for r in rows)
        best = max(rows, key=lambda r: r["WAR"])
        steps = [
            f"Batting runs: linear weights ({p.expr('linear_weights')}) minus the league's runs per PA x PA, "
            f"{'park-adjusted' if p.use_park_factors else 'no park adjustment'}.",
            f"Position runs per 162 games (C {p.pos_c:+g}, SS {p.pos_ss:+g}, 2B {p.pos_2b:+g}, 3B {p.pos_3b:+g}, CF {p.pos_cf:+g}, "
            f"LF/RF {p.pos_lf:+g}, 1B {p.pos_1b:+g}, DH {p.pos_dh:+g}); replacement {p.batting_replacement_runs:g} runs per 600 PA.",
            f"Pitching: (league RA9 x park - RA9) x IP/9 + {p.pitching_replacement_runs_per_9:g} x IP/9.",
            f"Runs per win: {p.expr('runs_per_win')} from the league's runs per game.",
            f"{len(rows)} seasons: batting {bat:.1f} + pitching {pit:.1f} = {total:.1f} WAR; best {best['yearID']} ({best['WAR']:.1f}).",
        ]
        table = [[str(r["yearID"]), r["teams"][:11], str(int(r["PA"])), f"{r['IP']:g}", f"{r['bWAR']:.1f}", f"{r['pWAR']:.1f}",
                  f"{r['WAR']:.1f}"] for r in rows]
        return self.prediction(
            inputs={"player": pid},
            outcomes=[Outcome("Career Open WAR", estimate=total), Outcome("Batting", estimate=bat, group="Parts"),
                      Outcome("Pitching", estimate=pit, group="Parts"),
                      Outcome(f"Best season ({best['yearID']})", estimate=best["WAR"], group="Parts")],
            steps=steps, tables=[Table("Season by season", ["Year", "Team", "PA", "IP", "Bat", "Pitch", "WAR"], table)],
            extras={"career": total, "seasons": {r["yearID"]: r["WAR"] for r in rows}},
        )
