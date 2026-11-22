"""The MLTT model's arithmetic: data loading, player ratings, game/match/Golden Game chances,
win probability, player and team stats, the season simulation. See MODEL.md.

Every tunable number comes from `p` (the model's Params); the only constants here are the
league's rules, which are params too (`game_to`, `golden_to`, ...), read once per call.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MATCHUPS = ("singles_1", "singles_2", "doubles", "singles_3", "singles_4")
MATCHUP_NAMES = {"singles_1": "Men's singles", "singles_2": "Women's singles", "doubles": "Doubles",
                 "singles_3": "Singles 3", "singles_4": "Singles 4"}


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ----------------------------------------------------------------------------------- data

@dataclass
class Game:
    season: int
    match_id: str
    date: str
    order: int  # matchup 1-5 in playing order
    matchup: str
    game: int  # 1-3 within the matchup
    team_a: str
    team_b: str
    a: tuple[str, ...]  # one player (singles) or two (doubles)
    b: tuple[str, ...]
    pa: int
    pb: int

    @property
    def index(self) -> int:
        """0-14: position of this game in the match's Stage One."""
        return (self.order - 1) * 3 + self.game - 1


@dataclass
class Match:
    season: int
    match_id: str
    date: str
    team_a: str
    team_b: str
    status: str
    stage: str
    city: str
    points_a: int = 0
    points_b: int = 0
    stage_one_a: int = 0
    stage_one_b: int = 0
    golden_a: int = 0
    golden_b: int = 0
    games: list[Game] = field(default_factory=list)
    golden_players: dict[str, list[tuple[str, int]]] = field(default_factory=dict)  # team -> [(player, rallies won)]

    @property
    def final(self) -> bool:
        return self.status == "final"

    @property
    def winner(self) -> str:
        return self.team_a if self.points_a > self.points_b else self.team_b


@dataclass
class Data:
    matches: list[Match]
    games: list[Game]
    players: dict[str, dict]
    teams: dict[str, dict]
    meta: dict
    history: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)  # spindex id -> [(date, old, new)]

    def rating_on(self, pid: str, as_of: str | None) -> float | None:
        """The player's SPINDEX rating before day `as_of`: the rating after their last rated result
        before that day, else their seed (first old rating) if it is real (> 0); None without a
        history. `as_of` None: the latest rating in the history."""
        sid = (self.players.get(pid) or {}).get("spindex_id")
        rows = self.history.get(sid or "")
        if not rows:
            return None
        before = [r for r in rows if as_of is None or r[0] < as_of]
        if before:
            return float(before[-1][2]) if before[-1][2] > 0 else None
        return float(rows[0][1]) if rows[0][1] > 0 else None

    def name(self, pid: str) -> str:
        return (self.players.get(pid) or {}).get("name") or pid[:8]

    def seasons(self) -> list[int]:
        return sorted({m.season for m in self.matches})

    def current_season(self) -> int:
        return max(self.seasons())


_CACHE: dict = {}


def load(data_dir: Path) -> Data:
    """Read data/*.csv (cached until the files change)."""
    import json
    files = [data_dir / n for n in ("matches.csv", "games.csv", "golden.csv", "players.csv", "teams.csv",
                                    "ratings_history.csv")]
    key = (str(data_dir), tuple(f.stat().st_mtime_ns for f in files))
    if key in _CACHE:
        return _CACHE[key]

    def rows(path: Path) -> list[dict]:
        with path.open(newline="") as fh:
            return list(csv.DictReader(fh))

    matches: dict[str, Match] = {}
    for r in rows(files[0]):
        m = Match(int(r["season"]), r["match_id"], r["date"], r["team_a"], r["team_b"], r["status"], r["stage"], r["city"])
        if m.final:
            m.points_a, m.points_b = int(r["points_a"]), int(r["points_b"])
            m.stage_one_a, m.stage_one_b = int(r["stage_one_a"]), int(r["stage_one_b"])
            m.golden_a, m.golden_b = int(r["golden_a"]), int(r["golden_b"])
        matches[m.match_id] = m
    games = []
    for r in rows(files[1]):
        g = Game(int(r["season"]), r["match_id"], r["date"], int(r["order"]), r["matchup"], int(r["game"]),
                 r["team_a"], r["team_b"], tuple(x for x in (r["a1"], r["a2"]) if x),
                 tuple(x for x in (r["b1"], r["b2"]) if x), int(r["points_a"]), int(r["points_b"]))
        games.append(g)
        matches[g.match_id].games.append(g)
    for r in rows(files[2]):
        matches[r["match_id"]].golden_players.setdefault(r["team"], []).append((r["player"], int(r["rallies_won"])))
    players = {r["player_id"]: r for r in rows(files[3])}
    teams = {r["team"]: r for r in rows(files[4])}
    meta_path = data_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    history: dict[str, list[tuple[str, int, int]]] = {}
    for r in rows(files[5]):
        history.setdefault(r["spindex_id"], []).append((r["date"], int(float(r["old_rating"] or 0)),
                                                         int(float(r["new_rating"] or 0))))
    data = Data(sorted(matches.values(), key=lambda m: (m.season, m.date)), games, players, teams, meta, history)
    _CACHE.clear()
    _CACHE[key] = data
    return data


# ---------------------------------------------------------------------- rules arithmetic

@lru_cache(maxsize=4096)
def game_win(q: float, to: int = 11) -> float:
    """Chance of winning a game to `to` points when each rally is won with chance q; at
    (to-1)-all the next rally wins (MLTT's golden point, no deuce)."""
    q = min(max(q, 1e-9), 1 - 1e-9)
    n = to - 1
    total = sum(math.comb(n + k, k) * q ** to * (1 - q) ** k for k in range(n))
    return total + math.comb(2 * n, n) * (q * (1 - q)) ** n * q


@lru_cache(maxsize=4096)
def race_win(head_a: int, head_b: int, q: float, to: int = 21) -> float:
    """Chance side A wins a race to `to` from head_a-head_b, rally chance q; at (to-1)-all one
    rally decides (the Golden Game's Ultimate Golden Point)."""
    @lru_cache(maxsize=None)
    def f(a: int, b: int) -> float:
        if a >= to:
            return 1.0
        if b >= to:
            return 0.0
        if a == b == to - 1:
            return q
        return q * f(a + 1, b) + (1 - q) * f(a, b + 1)
    return f(head_a, head_b)


@dataclass(frozen=True)
class Rules:
    game_to: int
    games_per_matchup: int
    golden_to: int
    golden_worth: int
    max_head_start: int

    @property
    def stage_one_games(self) -> int:
        return len(MATCHUPS) * self.games_per_matchup

    @property
    def total(self) -> int:
        return self.stage_one_games + self.golden_worth


def rules(p) -> Rules:
    return Rules(int(p.game_to), int(p.games_per_matchup), int(p.golden_to), int(p.golden_worth), int(p.max_head_start))


def head_start(lead: int, r: Rules) -> tuple[int, int]:
    """Golden Game starting score from team A's Stage One lead."""
    h = min(abs(lead), r.max_head_start)
    return (h, 0) if lead > 0 else (0, h)


def match_distribution(game_probs: list[float], q_golden: float, r: Rules) -> list[float]:
    """P(team A finishes with k team points), k = 0..total, from A's chance in each Stage One
    game still to play (independent) and A's rally chance in the Golden Game."""
    n = r.stage_one_games
    dist = [1.0]
    for g in game_probs:  # Stage One points distribution
        new = [0.0] * (len(dist) + 1)
        for k, pk in enumerate(dist):
            new[k] += pk * (1 - g)
            new[k + 1] += pk * g
        dist = new
    out = [0.0] * (r.total + 1)
    for s, ps in enumerate(dist):
        ha, hb = head_start(2 * s - n, r)
        pg = race_win(ha, hb, round(q_golden, 6), r.golden_to)
        out[s + r.golden_worth] += ps * pg
        out[s] += ps * (1 - pg)
    return out


def summarize(dist: list[float], r: Rules) -> tuple[float, float]:
    """(P(A wins the match), A's expected team points). A wins with more than half the points."""
    win = sum(pk for k, pk in enumerate(dist) if 2 * k > r.total)
    return win, sum(k * pk for k, pk in enumerate(dist))


@lru_cache(maxsize=64)
def _even_table(r: Rules) -> dict[tuple[int, int], float]:
    """Win probability for evenly matched teams: (Stage One games played, A's lead) -> P(A wins).
    Also (n, lead) = start of the Golden Game."""
    n = r.stage_one_games
    table = {}
    for played in range(n + 1):
        left = n - played
        for won in range(played + 1):
            lead = 2 * won - played
            # A's final Stage One points = won + Binomial(left, 0.5)
            p = 0.0
            for extra in range(left + 1):
                pe = math.comb(left, extra) / 2 ** left
                s = won + extra
                ha, hb = head_start(2 * s - n, r)
                pg = race_win(ha, hb, 0.5, r.golden_to)
                win_if_gg = 2 * (s + r.golden_worth) > r.total
                win_if_not = 2 * s > r.total
                p += pe * (pg * win_if_gg + (1 - pg) * win_if_not)
            table[(played, lead)] = p
    return table


def win_prob_even(played: int, lead: int, r: Rules) -> float:
    return _even_table(r)[(played, lead)]


# ------------------------------------------------------------------------------- ratings

@dataclass
class Ratings:
    value: dict[str, float]  # player -> rally edge (log-odds of winning a rally vs an average MLTT player)
    prior: dict[str, float]
    rallies: dict[str, float]  # weighted rallies that informed each rating
    as_of: str | None
    season: int

    def get(self, pid: str) -> float:
        return self.value.get(pid, self.prior.get(pid, 0.0))


def prior_means(data: Data, p, as_of: str | None = None) -> dict[str, float]:
    """Each player's prior edge from their MLTT rating: `rating_source` = "dated" uses the SPINDEX
    rating they had before `as_of` (no hindsight; no history: average), "current" today's rating."""
    out = {}
    for pid, row in data.players.items():
        if not p.use_rating_prior:
            out[pid] = 0.0
            continue
        if p.rating_source == "dated":
            rating = data.rating_on(pid, as_of)
        else:
            rating = float(row["mltt_rating"]) if row.get("mltt_rating") not in (None, "") else None
        out[pid] = p.formula("prior_mean", rating=rating) if rating is not None else 0.0
    return out


def fit_ratings(data: Data, p, as_of: str | None = None, season: int | None = None) -> Ratings:
    """Penalised maximum likelihood: every Stage One rally is a coin weighted by
    logistic(edge_A - edge_B) (doubles: the pair's average edge), each player's edge pulled
    toward their prior mean with the weight of `prior_rallies` rallies. Games before `as_of`
    only (walk-forward), older seasons down-weighted (formula `game_weight`)."""
    season = season or data.current_season()
    prior = prior_means(data, p, as_of)
    lam = float(p.prior_rallies) * 0.25  # a rally at even odds carries Fisher information 1/4
    obs: dict[str, list[tuple[int, float, float, int, tuple, tuple]]] = {}
    games = [g for g in data.games if (as_of is None or g.date < as_of) and g.season <= season]
    weights = {}
    for g in games:
        w = p.formula("game_weight", age=season - g.season, doubles=1.0 if g.matchup == "doubles" else 0.0)
        if w <= 0:
            continue
        weights[id(g)] = w
        for side, own, opp in ((1, g.a, g.b), (-1, g.b, g.a)):
            for pid in own:
                obs.setdefault(pid, []).append((side, w, 1.0 / len(own), id(g), own, opp))
    value = {pid: prior.get(pid, 0.0) for pid in obs}
    by_id = {id(g): g for g in games}
    rallies = {pid: sum(w * (by_id[gid].pa + by_id[gid].pb) for _, w, _, gid, _, _ in lst) for pid, lst in obs.items()}
    for _ in range(int(p.fit_iterations)):
        biggest = 0.0
        for pid, lst in obs.items():
            grad = -lam * (value[pid] - prior.get(pid, 0.0))
            hess = lam
            for side, w, c, gid, own, opp in lst:
                g = by_id[gid]
                diff = sum(value[x] for x in own) / len(own) - sum(value[x] for x in opp) / len(opp)
                q = logistic(diff)
                won, n = (g.pa, g.pa + g.pb) if side == 1 else (g.pb, g.pa + g.pb)
                grad += w * c * (won - n * q)
                hess += w * c * c * n * q * (1 - q)
            step = grad / hess
            value[pid] += step
            biggest = max(biggest, abs(step))
        if biggest < 1e-7:
            break
    return Ratings(value, prior, rallies, as_of, season)


# ------------------------------------------------------------------------------- lineups

def team_slots(data: Data, ratings: Ratings, team: str, season: int, as_of: str | None = None) -> dict[str, float]:
    """A team's expected edge in each matchup slot (and 'golden'), from who played it: the
    games-weighted average edge of the players the team used there this season before `as_of`
    (last season's when it has none yet; the team's average when a slot was never filled)."""
    for s in (season, season - 1):
        used: dict[str, dict[tuple, int]] = {}
        for g in data.games:
            if g.season != s or (as_of and g.date >= as_of):
                continue
            for t, own in ((g.team_a, g.a), (g.team_b, g.b)):
                if t == team:
                    d = used.setdefault(g.matchup, {})
                    d[own] = d.get(own, 0) + 1
        if used:
            break
    slots = {}
    for k in MATCHUPS:
        d = used.get(k) or {}
        tot = sum(d.values())
        if tot:
            slots[k] = sum(n * sum(ratings.get(x) for x in own) / len(own) for own, n in d.items()) / tot
    fallback = sum(slots.values()) / len(slots) if slots else 0.0
    for k in MATCHUPS:
        slots.setdefault(k, fallback)
    slots["golden"] = sum(slots[k] for k in MATCHUPS) / len(MATCHUPS)
    return slots


def slot_game_probs(sa: dict, sb: dict, p, r: Rules, shift: float = 0.0) -> tuple[list[float], float]:
    """Per Stage One game A's win chance, and A's Golden Game rally chance, from slot edges.
    `shift`: extra edge for A (the simulation's rating error)."""
    probs = []
    for k in MATCHUPS:
        q = p.formula("rally_prob", diff=sa[k] - sb[k] + shift)
        probs += [game_win(round(q, 6), r.game_to)] * r.games_per_matchup
    q_gg = p.formula("rally_prob", diff=sa["golden"] - sb["golden"] + shift)
    return probs, q_gg


# --------------------------------------------------------------------------- player stats

def player_season(data: Data, ratings: Ratings, season: int, p) -> dict[str, dict]:
    """Per player: games, record, rallies, 11-10 record, Points Above Average, WPA."""
    r = rules(p)
    out: dict[str, dict] = {}

    def row(pid: str, team: str) -> dict:
        d = out.setdefault(pid, {"player": pid, "name": data.name(pid), "team": team, "teams": set(), "games": 0,
                                 "won": 0.0, "rallies_won": 0.0, "rallies": 0.0, "close_won": 0.0, "close": 0.0,
                                 "paa": 0.0, "wpa": 0.0, "wpa_golden": 0.0, "singles": 0, "singles_won": 0,
                                 "golden_rallies": 0, "golden_games": 0})
        d["teams"].add(team)
        d["team"] = team
        return d

    for m in data.matches:
        if m.season != season or not m.final:
            continue
        lead, played = 0, 0
        for g in sorted(m.games, key=lambda g: g.index):
            before = win_prob_even(played, lead, r)
            a_won = g.pa > g.pb
            lead += 1 if a_won else -1
            played += 1
            swing = win_prob_even(played, lead, r) - before  # for team A
            close = max(g.pa, g.pb) == r.game_to and min(g.pa, g.pb) == r.game_to - 1
            for team, own, opp, won, rw, sign in ((g.team_a, g.a, g.b, a_won, g.pa, 1), (g.team_b, g.b, g.a, not a_won, g.pb, -1)):
                share = 1.0 / len(own)
                opp_edge = sum(ratings.get(x) for x in opp) / len(opp)
                expect = game_win(round(p.formula("rally_prob", diff=-opp_edge), 6), r.game_to)
                for pid in own:
                    d = row(pid, team)
                    d["games"] += 1
                    d["won"] += won
                    d["rallies_won"] += rw * share
                    d["rallies"] += (g.pa + g.pb) * share
                    if close:
                        d["close"] += share
                        d["close_won"] += won * share
                    d["paa"] += share * (won - expect)
                    d["wpa"] += share * sign * swing
                    if len(own) == 1:
                        d["singles"] += 1
                        d["singles_won"] += won
        # Golden Game: the swing from its start to the result is shared by the players who rotated in
        start = win_prob_even(r.stage_one_games, m.stage_one_a - m.stage_one_b, r)
        a_won_gg = m.golden_a > m.golden_b
        a_won_match = m.points_a > m.points_b
        swing = (1.0 if a_won_match else 0.0) - start
        for team, sign in ((m.team_a, 1), (m.team_b, -1)):
            lst = m.golden_players.get(team) or []
            for pid, won in lst:
                d = row(pid, team)
                d["wpa_golden"] += sign * swing / len(lst)
                d["wpa"] += sign * swing / len(lst)
                d["golden_rallies"] += won
                d["golden_games"] += 1
        _ = a_won_gg
    for d in out.values():
        d["edge"] = ratings.get(d["player"])
        d["game_vs_avg"] = game_win(round(p.formula("rally_prob", diff=d["edge"]), 6), r.game_to)
        d["teams"] = sorted(d["teams"])
    return out


# ----------------------------------------------------------------------------- team stats

def team_season(data: Data, ratings: Ratings, season: int, p, as_of: str | None = None) -> dict[str, dict]:
    """Standings plus: points %, expected points from rally shares (luck = actual - expected),
    11-10 record, and strength of schedule (opponents' average slot edge), played and to come."""
    r = rules(p)
    out: dict[str, dict] = {}
    strength = {t: team_slots(data, ratings, t, season, as_of) for t in data.teams}

    def row(t: str) -> dict:
        return out.setdefault(t, {"team": t, "division": (data.teams.get(t) or {}).get("division", ""), "played": 0,
                                  "w": 0, "l": 0, "pf": 0, "pa": 0, "xpf": 0.0, "rallies_won": 0, "rallies": 0,
                                  "close_won": 0, "close": 0, "gg_w": 0, "opp": [], "opp_left": [], "left": 0})

    for m in data.matches:
        if m.season != season or m.stage != "regular":
            continue
        if not m.final or (as_of and m.date >= as_of):
            for t, o in ((m.team_a, m.team_b), (m.team_b, m.team_a)):
                row(t)["opp_left"].append(strength.get(o, {}).get("golden", 0.0))
                row(t)["left"] += 1
            continue
        for t, o, pf, pa, gf, ga in ((m.team_a, m.team_b, m.points_a, m.points_b, m.golden_a, m.golden_b),
                                     (m.team_b, m.team_a, m.points_b, m.points_a, m.golden_b, m.golden_a)):
            d = row(t)
            d["played"] += 1
            d["w" if pf > pa else "l"] += 1
            d["pf"] += pf
            d["pa"] += pa
            d["gg_w"] += gf > ga
            d["opp"].append(strength.get(o, {}).get("golden", 0.0))
        # expected points from each matchup's rally share
        xa = 0.0
        for k in MATCHUPS:
            gs = [g for g in m.games if g.matchup == k]
            ra, n = sum(g.pa for g in gs), sum(g.pa + g.pb for g in gs)
            if n:
                xa += len(gs) * game_win(round(ra / n, 6), r.game_to)
        ra, rb = sum(g.pa for g in m.games), sum(g.pb for g in m.games)
        ha, hb = head_start(m.stage_one_a - m.stage_one_b, r)
        ga, gb = m.golden_a - ha, m.golden_b - hb  # rallies won in the Golden Game itself
        q_gg = ga / (ga + gb) if ga + gb > 0 else 0.5
        x_gg = race_win(ha, hb, round(q_gg, 6), r.golden_to) * r.golden_worth
        xa += x_gg
        for t, x, rw, rt in ((m.team_a, xa, ra, ra + rb), (m.team_b, r.total - xa, rb, ra + rb)):
            d = out[t]
            d["xpf"] += x
            d["rallies_won"] += rw
            d["rallies"] += rt
        for g in m.games:
            if max(g.pa, g.pb) == r.game_to and min(g.pa, g.pb) == r.game_to - 1:
                for t, won in ((m.team_a, g.pa > g.pb), (m.team_b, g.pb > g.pa)):
                    out[t]["close"] += 1
                    out[t]["close_won"] += won
    for t, d in out.items():
        tot = d["pf"] + d["pa"]
        d["pct"] = d["pf"] / tot if tot else None
        d["xpct"] = d["xpf"] / tot if tot else None
        d["luck"] = d["pf"] - d["xpf"]
        d["rally_pct"] = d["rallies_won"] / d["rallies"] if d["rallies"] else None
        d["sos"] = sum(d["opp"]) / len(d["opp"]) if d["opp"] else None
        d["sos_left"] = sum(d["opp_left"]) / len(d["opp_left"]) if d["opp_left"] else None
        d["strength"] = strength.get(t, {}).get("golden", 0.0)
    return out


# ------------------------------------------------------------------------ season simulation

def simulate_season(data: Data, ratings: Ratings, season: int, p, as_of: str | None = None) -> dict:
    """Monte Carlo of the rest of the regular season and the Final Four. Each run draws a rating
    error per team (sd `team_rating_sd`); each remaining match's points are drawn from its exact
    distribution (match_distribution) at that error, on a grid of `sim_grid_step`."""
    r = rules(p)
    rng = random.Random(int(p.seed))
    teams = sorted({t for m in data.matches if m.season == season for t in (m.team_a, m.team_b)})
    division = {t: (data.teams.get(t) or {}).get("division", "") for t in teams}
    slots = {t: team_slots(data, ratings, t, season, as_of) for t in teams}
    base_pf = {t: 0 for t in teams}
    base_pa = {t: 0 for t in teams}
    left = []
    for m in data.matches:
        if m.season != season or m.stage != "regular":
            continue
        if m.final and (as_of is None or m.date < as_of):
            base_pf[m.team_a] += m.points_a
            base_pa[m.team_a] += m.points_b
            base_pf[m.team_b] += m.points_b
            base_pa[m.team_b] += m.points_a
        else:
            left.append(m)
    step = float(p.sim_grid_step)
    sd = float(p.team_rating_sd)
    span = int(math.ceil(4 * sd * math.sqrt(2) / step)) if step > 0 and sd > 0 else 0

    @lru_cache(maxsize=None)
    def cdf(a: str, b: str, k: int) -> tuple[float, ...]:
        probs, q_gg = slot_game_probs(slots[a], slots[b], p, r, shift=k * step)
        dist = match_distribution(probs, q_gg, r)
        acc, c = 0.0, []
        for x in dist:
            acc += x
            c.append(acc)
        return tuple(c)

    def draw(a: str, b: str, err: dict) -> int:
        k = max(-span, min(span, round((err[a] - err[b]) / step))) if span else 0
        u = rng.random()
        for pts, c in enumerate(cdf(a, b, k)):
            if u <= c:
                return pts
        return r.total

    def play(a: str, b: str, err: dict) -> str:
        return a if 2 * draw(a, b, err) > r.total else b

    n = int(p.simulations)
    tallies = {t: {"pts": 0.0, "pct": 0.0, "div1": 0, "playoff": 0, "final": 0, "champ": 0, "seed_pcts": []} for t in teams}
    for _ in range(n):
        err = {t: rng.gauss(0, sd) for t in teams}
        pf, pa = dict(base_pf), dict(base_pa)
        for m in left:
            x = draw(m.team_a, m.team_b, err)
            pf[m.team_a] += x
            pa[m.team_a] += r.total - x
            pf[m.team_b] += r.total - x
            pa[m.team_b] += x
        pct = {t: pf[t] / (pf[t] + pa[t]) if pf[t] + pa[t] else 0.5 for t in teams}
        order = sorted(teams, key=lambda t: (-pct[t], rng.random()))  # ties broken at random
        if p.playoff_rule == "division_top2":
            divs = sorted({division[t] for t in teams})
            tops = {d: [t for t in order if division[t] == d][:2] for d in divs}
            if len(divs) == 2:
                (d1, d2) = divs
                semis = [(tops[d1][0], tops[d2][1]), (tops[d2][0], tops[d1][1])]
            else:  # fall back to the overall order
                f4 = order[:4]
                semis = [(f4[0], f4[3]), (f4[1], f4[2])]
            for d in divs:
                tallies[tops[d][0]]["div1"] += 1
        else:
            f4 = order[:4]
            semis = [(f4[0], f4[3]), (f4[1], f4[2])]
        finalists = [play(a, b, err) for a, b in semis]
        champ = play(finalists[0], finalists[1], err)
        for a, b in semis:
            tallies[a]["playoff"] += 1
            tallies[b]["playoff"] += 1
        for t in finalists:
            tallies[t]["final"] += 1
        tallies[champ]["champ"] += 1
        for t in teams:
            tallies[t]["pts"] += pf[t]
            tallies[t]["pct"] += pct[t]
    for t, d in tallies.items():
        for k in ("pts", "pct"):
            d[k] /= n
        for k in ("div1", "playoff", "final", "champ"):
            d[k] /= n
        del d["seed_pcts"]
    return {"teams": tallies, "remaining": len(left), "simulations": n, "slots": slots}
