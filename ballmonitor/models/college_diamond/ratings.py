"""Team strength for college_diamond: weighted ridge run-margin ratings (stdlib only).

For every game g (home h, away a) with transformed margin y_g = T(home runs - away runs):

    y_g ~ (r_h - r_a) + k_g * (m_h - m_a) + H * x_g

    r_t  weekend rating (runs per game vs an average D-I team, neutral site, weekend
         pitching), used for weekend series and every postseason game
    m_t  team's midweek offset (k_g = 1 for midweek games: Mon-Thu games that are not part
         of a multi-game series), shrunk toward beta * r_t (good teams drop more midweek)
    H    home-field edge in runs (x_g = 1 unless the site is known to be neutral)

minimising   sum_g w_g (y_g - pred_g)^2 + lam_r * sum_t (r_t - p_t)^2
                                         + lam_m * sum_t (m_t - beta * r_t)^2

w_g = recency decay * (midweek_weight if midweek) ; p_t = preseason prior (last season's
rating times prior_carry, else 0). T(y) = sign(y) * min(|y|, margin_cap) ** margin_power.
The system is solved by block Gauss-Seidel sweeps (no numpy). research.py fits the same
objective with numpy and checks both agree.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field

from ballmonitor.models.college_diamond.data import Game


@dataclass
class RatingParams:
    margin_cap: float = 10.0
    margin_power: float = 1.0
    ridge: float = 4.0            # lam_r, in games
    midweek_ridge: float = 8.0    # lam_m, in games
    midweek_beta: float = 0.0     # m_t prior mean = beta * r_t
    midweek_weight: float = 1.0   # weight of midweek games
    half_life_days: float = 0.0   # 0 = no recency decay
    prior_carry: float = 0.0      # p_t = prior_carry * last season rating
    split_midweek: bool = True
    postseason_weight: float = 1.0


@dataclass
class Ratings:
    weekend: dict[str, float]
    midweek: dict[str, float]          # offsets m_t
    home_edge: float
    resid_sd: float
    games: int
    played: dict[str, int] = field(default_factory=dict)

    def diff(self, a: str, b: str, midweek: bool = False, home: float = 0.0) -> float:
        """Expected transformed margin of a over b (home = +1 a at home, -1 b at home)."""
        d = self.weekend.get(a, 0.0) - self.weekend.get(b, 0.0)
        if midweek:
            d += self.midweek.get(a, 0.0) - self.midweek.get(b, 0.0)
        return d + home * self.home_edge


def transform(margin: float, cap: float, power: float) -> float:
    s = 1.0 if margin > 0 else -1.0 if margin < 0 else 0.0
    return s * min(abs(margin), cap) ** power


def midweek_flags(games: list[Game]) -> list[bool]:
    """Midweek = Mon-Thu game whose pair does not also play within one day (a Thursday
    game that opens a Thu-Sat series counts as a weekend game)."""
    by_pair: dict[frozenset, list[dt.date]] = defaultdict(list)
    for g in games:
        by_pair[frozenset((g.home, g.away))].append(g.day)
    out = []
    for g in games:
        if g.game_type != "R" or g.weekday >= 4:
            out.append(False)
            continue
        days = by_pair[frozenset((g.home, g.away))]
        near = sum(1 for d in days if abs((d - g.day).days) <= 1)
        out.append(near <= 1)
    return out


def fit(games: list[Game], params: RatingParams, as_of: dt.date | None = None,
        prior: dict[str, float] | None = None, flags: list[bool] | None = None,
        sweeps: int = 400, tol: float = 1e-6) -> Ratings:
    prior = prior or {}
    flags = flags if flags is not None else midweek_flags(games)
    teams = sorted({g.home for g in games} | {g.away for g in games} | set(prior))
    ref = as_of or (max(g.day for g in games) if games else dt.date.today())
    rows = []  # (h, a, y, w, x, k)
    for g, mid in zip(games, flags):
        w = 1.0
        if params.half_life_days > 0:
            w *= 0.5 ** (max((ref - g.day).days, 0) / params.half_life_days)
        k = 1.0 if (mid and params.split_midweek) else 0.0
        if mid:
            w *= params.midweek_weight
        if g.game_type == "N":
            w *= params.postseason_weight
        rows.append((g.home, g.away, transform(g.margin, params.margin_cap, params.margin_power),
                     w, 0.0 if g.neutral else 1.0, k))
    adj: dict[str, list[tuple]] = defaultdict(list)
    for h, a, y, w, x, k in rows:
        adj[h].append((a, y, w, x, k, 1.0))
        adj[a].append((h, -y, w, -x, k, -1.0))
    r = {t: prior.get(t, 0.0) for t in teams}
    m = {t: 0.0 for t in teams}
    H = 0.0
    lam, lam_m, beta = params.ridge, params.midweek_ridge, params.midweek_beta
    venue = [(h, a, y, w, x, k) for h, a, y, w, x, k in rows if x]
    for _ in range(sweeps):
        delta = 0.0
        if venue:
            num = sum(w * (y - (r[h] - r[a]) - k * (m[h] - m[a])) for h, a, y, w, x, k in venue)
            den = sum(w for *_, w, x, k in venue)
            H_new = num / den if den else 0.0
            delta = max(delta, abs(H_new - H))
            H = H_new
        for t in teams:
            lst = adj.get(t, ())
            # r_t update (m fixed); the m-prior term beta * r_t couples r_t to m_t
            num = lam * prior.get(t, 0.0) + lam_m * beta * m[t]
            den = lam + lam_m * beta * beta
            for o, y, w, x, k, _s in lst:
                num += w * (y - H * x + r[o] - k * (m[t] - m[o]))
                den += w
            new_r = num / den if den else 0.0
            delta = max(delta, abs(new_r - r[t]))
            r[t] = new_r
            if params.split_midweek:
                num = lam_m * beta * r[t]
                den = lam_m
                for o, y, w, x, k, _s in lst:
                    if k:
                        num += w * (y - H * x - (r[t] - r[o]) + m[o])
                        den += w
                new_m = num / den if den else 0.0
                delta = max(delta, abs(new_m - m[t]))
                m[t] = new_m
        if delta < tol:
            break
    ssr = sum(w * (y - (r[h] - r[a]) - k * (m[h] - m[a]) - H * x) ** 2 for h, a, y, w, x, k in rows)
    wsum = sum(w for *_, w, x, k in rows) or 1.0
    played = defaultdict(int)
    for g in games:
        played[g.home] += 1
        played[g.away] += 1
    return Ratings(r, m, H, math.sqrt(ssr / wsum), len(rows), dict(played))
