"""NCAA Rating Percentage Index (stdlib only).

    RPI = w_wp * WP + w_owp * OWP + w_oowp * OOWP          (NCAA: 0.25 / 0.50 / 0.25)

WP    the team's winning percentage in D-I games. Baseball (since 2013) weights each
      result by site: a home win counts `home_win` (0.7), a road win `road_win` (1.3), a
      neutral win 1.0; a home loss counts `home_loss` (1.3), a road loss `road_loss` (0.7).
OWP   for each game played, the opponent's (unweighted) winning percentage excluding its
      games against the team; averaged over games (an opponent met three times counts
      three times).
OOWP  the average over games of the opponents' OWP.

The NCAA's unpublished bonus/penalty adjustments are not reproduced. Ties count half.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class RpiWeights:
    w_wp: float = 0.25
    w_owp: float = 0.50
    w_oowp: float = 0.25
    home_win: float = 0.7
    road_win: float = 1.3
    home_loss: float = 1.3
    road_loss: float = 0.7


def rpi(results, weights: RpiWeights = RpiWeights()) -> dict[str, float]:
    """results: iterable of (home, away, home_result, neutral) with home_result 1 (home
    won), 0 (away won) or 0.5 (tie). Returns team -> RPI."""
    wins = defaultdict(float)       # unweighted
    games = defaultdict(float)
    ww = defaultdict(float)         # weighted wins / losses
    wl = defaultdict(float)
    h2h_w: dict[tuple[str, str], float] = defaultdict(float)
    h2h_g: dict[tuple[str, str], float] = defaultdict(float)
    opp_list: dict[str, list[str]] = defaultdict(list)
    for h, a, res, neutral in results:
        games[h] += 1
        games[a] += 1
        wins[h] += res
        wins[a] += 1 - res
        h2h_w[(h, a)] += res
        h2h_w[(a, h)] += 1 - res
        h2h_g[(h, a)] += 1
        h2h_g[(a, h)] += 1
        opp_list[h].append(a)
        opp_list[a].append(h)
        if neutral:
            ww[h] += res
            wl[h] += 1 - res
            ww[a] += 1 - res
            wl[a] += res
        else:
            ww[h] += res * weights.home_win
            wl[h] += (1 - res) * weights.home_loss
            ww[a] += (1 - res) * weights.road_win
            wl[a] += res * weights.road_loss
    teams = list(games)
    wp = {t: ww[t] / (ww[t] + wl[t]) if ww[t] + wl[t] else 0.0 for t in teams}
    owp = {}
    for t in teams:
        tot = 0.0
        for o in opp_list[t]:
            g = games[o] - h2h_g[(o, t)]
            tot += (wins[o] - h2h_w[(o, t)]) / g if g > 0 else 0.0
        owp[t] = tot / len(opp_list[t]) if opp_list[t] else 0.0
    oowp = {t: sum(owp[o] for o in opp_list[t]) / len(opp_list[t]) if opp_list[t] else 0.0 for t in teams}
    return {t: weights.w_wp * wp[t] + weights.w_owp * owp[t] + weights.w_oowp * oowp[t] for t in teams}


def ranks(values: dict[str, float]) -> dict[str, int]:
    order = sorted(values, key=lambda t: (-values[t], t))
    return {t: i + 1 for i, t in enumerate(order)}


class RpiState:
    """Fast repeated RPI: fixed (completed) results are accumulated once; each call adds a
    simulation's extra results. Same definition as rpi(); used by the Monte Carlo."""

    def __init__(self, results, weights: RpiWeights = RpiWeights()):
        self.w = weights
        self.wins: dict[str, float] = defaultdict(float)
        self.games: dict[str, float] = defaultdict(float)
        self.ww: dict[str, float] = defaultdict(float)
        self.wl: dict[str, float] = defaultdict(float)
        self.h2h_w: dict[tuple[str, str], float] = defaultdict(float)
        self.h2h_g: dict[tuple[str, str], float] = defaultdict(float)
        self._add(results, self.wins, self.games, self.ww, self.wl, self.h2h_w, self.h2h_g)

    def _add(self, results, wins, games, ww, wl, h2h_w, h2h_g):
        w = self.w
        for h, a, res, neutral in results:
            games[h] += 1
            games[a] += 1
            wins[h] += res
            wins[a] += 1 - res
            h2h_w[(h, a)] += res
            h2h_w[(a, h)] += 1 - res
            h2h_g[(h, a)] += 1
            h2h_g[(a, h)] += 1
            if neutral:
                ww[h] += res
                wl[h] += 1 - res
                ww[a] += 1 - res
                wl[a] += res
            else:
                ww[h] += res * w.home_win
                wl[h] += (1 - res) * w.home_loss
                ww[a] += (1 - res) * w.road_win
                wl[a] += res * w.road_loss

    def compute(self, extra=()) -> dict[str, float]:
        wins, games = dict(self.wins), dict(self.games)
        ww, wl = dict(self.ww), dict(self.wl)
        h2h_w, h2h_g = dict(self.h2h_w), dict(self.h2h_g)
        dd = defaultdict
        wins, games, ww, wl = dd(float, wins), dd(float, games), dd(float, ww), dd(float, wl)
        h2h_w, h2h_g = dd(float, h2h_w), dd(float, h2h_g)
        self._add(extra, wins, games, ww, wl, h2h_w, h2h_g)
        opps: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (t, o), c in h2h_g.items():
            opps[t].append((o, c))
        owp = {}
        for t, lst in opps.items():
            tot = 0.0
            for o, c in lst:
                g = games[o] - c
                if g > 0:
                    tot += c * (wins[o] - h2h_w[(o, t)]) / g
            owp[t] = tot / games[t] if games[t] else 0.0
        w = self.w
        out = {}
        for t, lst in opps.items():
            oowp = sum(c * owp[o] for o, c in lst) / games[t] if games[t] else 0.0
            d = ww[t] + wl[t]
            out[t] = w.w_wp * (ww[t] / d if d else 0.0) + w.w_owp * owp[t] + w.w_oowp * oowp
        return out
