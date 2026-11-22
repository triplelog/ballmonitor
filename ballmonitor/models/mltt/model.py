"""Major League Table Tennis. See MODEL.md.

Three kinds of run (inputs `kind`):
  match    team_a vs team_b: win chances, expected team points, slot by slot   (backtested)
  season   standings with expected points / luck / strength of schedule + Final Four odds
  players  leaderboards: rally edge, points above average, win probability added
"""

from __future__ import annotations

from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.prediction import Table

from . import engine as E


class MlttModel(BaseModel):
    def data(self) -> E.Data:
        return E.load(self.dir / "data")

    def ratings(self, season: int | None = None, as_of: str | None = None) -> E.Ratings:
        return E.fit_ratings(self.data(), self.params, as_of=as_of, season=season)

    # ------------------------------------------------------------------------------
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        kind = str(inputs.get("kind", "match"))
        if kind == "match":
            return self._match(inputs)
        if kind == "season":
            return self._season(inputs)
        if kind == "players":
            return self._players(inputs)
        raise ValueError(f"kind must be match, season or players, got {kind!r}")

    def _common(self, inputs: dict) -> tuple[E.Data, int, str | None, list[str]]:
        data = self.data()
        season = int(inputs.get("season") or data.current_season())
        as_of = str(inputs["as_of"]) if inputs.get("as_of") else None
        p = self.params
        steps = [f"Data: {sum(m.final for m in data.matches)} played matches, {len(data.games)} Stage One games "
                 f"(MLTT results API, last result {data.meta.get('last_result', '?')})."
                 + (f" Only games before {as_of} are used." if as_of else "")]
        steps.append(
            f"Edges: each Stage One rally is won with chance {p.expr('rally_prob')} (diff = own edge - "
            f"opponent's; doubles: pair average); prior edge {p.expr('prior_mean')}"
            + ("" if p.use_rating_prior else " (off: prior 0)")
            + f" worth {p.prior_rallies:g} rallies; game weight {p.expr('game_weight')}.")
        return data, season, as_of, steps

    # ------------------------------------------------------------------------- match
    def _match(self, inputs: dict) -> Prediction:
        data, season, as_of, steps = self._common(inputs)
        p, r = self.params, E.rules(self.params)
        a, b = str(inputs["team_a"]), str(inputs["team_b"])
        for t in (a, b):
            if t not in data.teams:
                raise ValueError(f"unknown team {t!r}; teams: {', '.join(sorted(data.teams))}")
        R = E.fit_ratings(data, p, as_of=as_of, season=season)
        sa = E.team_slots(data, R, a, season, as_of)
        sb = E.team_slots(data, R, b, season, as_of)
        steps.append(f"Fitted {len(R.value)} players' edges. Lineup guess: each slot's games-weighted average "
                     f"edge of the players the team used there in Season {season}"
                     + (" before that date." if as_of else "."))
        # average over the team-error spread (3-point Gauss-Hermite on the difference of two errors)
        sd = float(p.team_rating_sd) * 2 ** 0.5
        nodes = [(-sd * 3 ** 0.5, 1 / 6), (0.0, 2 / 3), (sd * 3 ** 0.5, 1 / 6)] if sd > 0 else [(0.0, 1.0)]
        dist = [0.0] * (r.total + 1)
        for shift, w in nodes:
            gp, q_gg = E.slot_game_probs(sa, sb, p, r, shift)
            for k, x in enumerate(E.match_distribution(gp, q_gg, r)):
                dist[k] += w * x
        win, xa = E.summarize(dist, r)
        gp, q_gg = E.slot_game_probs(sa, sb, p, r)
        rows = []
        for i, k in enumerate(E.MATCHUPS):
            g = gp[i * r.games_per_matchup]
            rows.append([E.MATCHUP_NAMES[k], f"{sa[k]:+.3f}", f"{sb[k]:+.3f}", f"{g:.1%}", f"{g * r.games_per_matchup:.2f}"])
        rows.append(["Golden Game (rally)", f"{sa['golden']:+.3f}", f"{sb['golden']:+.3f}", f"{q_gg:.1%}", ""])
        steps.append(f"Each game: P(win) from the rally chance q, games to {r.game_to}, golden point at "
                     f"{r.game_to - 1}-all; {r.games_per_matchup} games per matchup, all played.")
        steps.append(f"Golden Game: race to {r.golden_to}, leader starts ahead by its lead (max {r.max_head_start}), "
                     f"worth {r.golden_worth}; exact distribution of {a}'s team points over all "
                     f"{r.stage_one_games} Stage One results, averaged over a team-edge error (sd {p.team_rating_sd:g}).")
        steps.append(f"P({a} wins) = P(more than {r.total // 2} of {r.total} points) = {win:.3f}; expected "
                     f"points {xa:.2f}-{r.total - xa:.2f}.")
        lo, hi = _quantile(dist, 0.1), _quantile(dist, 0.9)
        gg_decides = sum(dist_s for dist_s in _stage_one_close(sa, sb, p, r))
        return self.prediction(
            inputs={"match": f"{a} vs {b}", "season": season, "as of": as_of or "latest data"},
            outcomes=[
                Outcome(f"{a} wins", probability=win, group="Match"),
                Outcome(f"{b} wins", probability=1 - win, group="Match"),
                Outcome(f"{a} team points", estimate=xa, interval=(lo, hi), fmt="number", group="Team points"),
                Outcome(f"{b} team points", estimate=r.total - xa, interval=(r.total - hi, r.total - lo), fmt="number",
                        group="Team points"),
                Outcome("Golden Game can swing it", probability=gg_decides, group="Match",
                        note="Stage One leaves the winner open"),
            ],
            steps=steps, interval_level=0.8,
            tables=[Table("Slot by slot (edge = rally log-odds vs an average MLTT player)",
                          ["Matchup", _short(a), _short(b), f"{_short(a)} wins game", "Exp. games"], rows)],
            extras={"p_win": win, "points_a": xa, "slots_a": sa, "slots_b": sb, "distribution": dist},
        )

    # ------------------------------------------------------------------------ season
    def _season(self, inputs: dict) -> Prediction:
        data, season, as_of, steps = self._common(inputs)
        p = self.params
        R = E.fit_ratings(data, p, as_of=as_of, season=season)
        teams = E.team_season(data, R, season, p, as_of)
        sim = E.simulate_season(data, R, season, p, as_of)
        steps.append("Expected points: each matchup's rally share -> chance per game; Golden Game rally share "
                     "from the actual head start; luck = points - expected points.")
        steps.append("Strength of schedule: opponents' average edge (their five slots), played and still to play.")
        steps.append(f"Simulated the {sim['remaining']} remaining regular-season matches {sim['simulations']} times "
                     f"(team error sd {p.team_rating_sd:g}); Final Four by {p.playoff_rule}; one-match semis and final.")
        order = sorted(teams.values(), key=lambda d: (d["division"], -(d["pct"] or 0)))
        outcomes = []
        for d in sorted(teams.values(), key=lambda d: -sim["teams"][d["team"]]["playoff"]):
            s = sim["teams"][d["team"]]
            outcomes.append(Outcome(f"{d['team']}: Final Four", probability=s["playoff"], group=f"Final Four",
                                    note=f"proj. {s['pct']:.1%} of points"))
        for d in sorted(teams.values(), key=lambda d: -sim["teams"][d["team"]]["champ"]):
            outcomes.append(Outcome(f"{d['team']}: champion", probability=sim["teams"][d["team"]]["champ"],
                                    group="MLTT Cup"))
        rows = []
        for d in order:
            rows.append([d["team"], d["division"], f"{d['w']}-{d['l']}", _pct(d["pct"]), _pct(d["xpct"]),
                         f"{d['luck']:+.1f}", _pct(d["rally_pct"]), f"{d['close_won']}-{d['close'] - d['close_won']}",
                         _edge(d["sos"]), _edge(d["sos_left"])])
        return self.prediction(
            inputs={"season": season, "as of": as_of or "latest data"},
            outcomes=outcomes, steps=steps,
            tables=[Table("Standings plus", ["Team", "Div", "W-L", "Pts %", "Exp %", "Luck", "Rally %", "11-10",
                                             "SOS", "SOS left"], rows,
                          note="Pts % ranks the standings. Luck = team points minus expected. SOS = opponents' "
                               "average edge.")],
            extras={"teams": teams, "simulation": sim["teams"]},
        )

    # ----------------------------------------------------------------------- players
    def _players(self, inputs: dict) -> Prediction:
        data, season, as_of, steps = self._common(inputs)
        p = self.params
        top = int(inputs.get("top", 10))
        R = E.fit_ratings(data, p, as_of=as_of, season=season)
        stats = E.player_season(data, R, season, p)
        steps.append("Points above average: per game, won (1/0) minus the chance an average MLTT player would "
                     "have won it against the same opponent(s); doubles half each.")
        steps.append("Win probability added: change in the chance of winning the match (table for even teams) "
                     "over each game; doubles half each; the Golden Game's swing shared by its players.")
        players = [d for d in stats.values() if d["games"]]
        outcomes = []
        for d in sorted(players, key=lambda d: -d["wpa"])[:top]:
            outcomes.append(Outcome(f"{d['name']} ({_short(d['team'])})", estimate=d["wpa"], fmt="number",
                                    group="Win probability added (matches)"))
        for d in sorted(players, key=lambda d: -d["paa"])[:top]:
            outcomes.append(Outcome(f"{d['name']} ({_short(d['team'])})", estimate=d["paa"], fmt="number",
                                    group="Team points above average"))
        rows = [[d["name"], _short(d["team"]), str(d["games"]), f"{d['won']:.0f}", _pct(d["rallies_won"] / d["rallies"]),
                 f"{d['edge']:+.2f}", _pct(d["game_vs_avg"]), f"{d['paa']:+.1f}", f"{d['wpa']:+.2f}"]
                for d in sorted(players, key=lambda d: -d["edge"])[:top]]
        return self.prediction(
            inputs={"season": season, "as of": as_of or "latest data", "top": top},
            outcomes=outcomes, steps=steps,
            tables=[Table(f"Top {top} by rally edge", ["Player", "Team", "G", "W", "Rally %", "Edge", "vs avg",
                                                       "PAA", "WPA"], rows,
                          note="Edge: rally log-odds vs an average MLTT player. vs avg: chance to beat one in a game.")],
            extras={"players": {k: dict(v) for k, v in stats.items()}},
        )

    # ---------------------------------------------------------------------- backtest
    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        # data/backtest.csv: season,date,stage,team_a,team_b,points_a,points_b,winner
        return ({"kind": "match", "team_a": row["team_a"], "team_b": row["team_b"], "season": row["season"],
                 "as_of": row["date"]}, f"{row['winner']} wins")

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        # only the two "wins" outcomes are mutually exclusive
        a, b = prediction.outcomes[0], prediction.outcomes[1]
        pa = a.probability or 0.0
        y = 1.0 if actual == a.label else 0.0
        import math
        return {"brier": (pa - y) ** 2, "log_loss": -math.log(max(pa if y else 1 - pa, 1e-12)),
                "top_pick_correct": float((pa >= 0.5) == bool(y))}


def _stage_one_close(sa, sb, p, r) -> list[float]:
    """P(Stage One ends where the Golden Game can still change the winner), as a one-item list."""
    gp, _ = E.slot_game_probs(sa, sb, p, r)
    dist = [1.0]
    for g in gp:
        new = [0.0] * (len(dist) + 1)
        for k, x in enumerate(dist):
            new[k] += x * (1 - g)
            new[k + 1] += x * g
        dist = new
    lo = r.total // 2 + 1 - r.golden_worth  # with the Golden Game A reaches a majority
    hi = r.total // 2                        # without it A falls short
    return [sum(x for s, x in enumerate(dist) if lo <= s <= hi)]


def _quantile(dist: list[float], q: float) -> float:
    acc = 0.0
    for k, x in enumerate(dist):
        acc += x
        if acc >= q:
            return float(k)
    return float(len(dist) - 1)


def _pct(x) -> str:
    return "" if x is None else f"{x:.1%}"


def _edge(x) -> str:
    return "" if x is None else f"{x:+.2f}"


def _short(team: str) -> str:
    return team.split()[-1] if team else ""
