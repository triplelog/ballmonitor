"""Season + postseason Monte Carlo for college_diamond (stdlib only).

One simulation:
 1. Remaining regular-season games (the actual schedule after `as_of`) are played with
    P(home win) = win_probability(diff), diff = rating difference (+ home edge), where
    every team's rating carries a per-simulation draw of its rating uncertainty.
 2. Conference standings (conference win %, head-to-head then coin flip) seed each
    conference tournament, played per data/conference_formats.json (single/double
    elimination, pods, pool play, title series, or none). The automatic bid goes to the
    tournament champion, or to the regular-season champion where that is the rule.
 3. RPI is recomputed from all D-I results; the committee proxy scores every team from its
    RPI rank, rating rank and D-I win % (config formulas selection_score / host_score)
    plus logistic noise; the best non-automatic teams fill the 64-team field.
 4. 16 hosts (= the 16 national seeds) and seed lines follow the host/selection scores;
    regionals are filled on an S-curve with conference-mates kept apart.
 5. Regionals (4-team double elimination, host at home), super regionals (best of 3,
    national seed 1 v 16, 2 v 15 ...), and the World Series (two 4-team double-
    elimination brackets, best-of-3 finals) are played game by game with weekend ratings.
Everything tunable comes from Params (config.toml); see MODEL.md.
"""

from __future__ import annotations

import bisect
import datetime as dt
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from ballmonitor.models.college_diamond.data import Game
from ballmonitor.models.college_diamond.rpi import RpiState, RpiWeights, ranks

DIFF_LIMIT = 30.0     # win-probability table range (transformed-margin units)
DIFF_STEP = 0.01
SEL_POOL_RPI = 200   # RPI rank beyond which a team is not scored for an at-large bid
CWS_BRACKETS = ([1, 16, 8, 9, 4, 13, 5, 12], [2, 15, 7, 10, 3, 14, 6, 11])  # national-seed slots


@dataclass
class SimInputs:
    sport: str
    season: int
    as_of: dt.date
    teams: dict[str, dict]                 # id -> {name, conference}
    completed: list[Game]                  # all D-I games before as_of (any type)
    remaining: list[tuple[Game, bool]]     # remaining regular-season games, midweek flag
    rating: dict[str, float]               # weekend rating
    midweek: dict[str, float]              # midweek offsets (0 if not split)
    home_edge: float
    rating_sd: dict[str, float]            # per-team sd of the rating draw
    formats: dict[str, dict]               # conference -> format entry
    done_champions: dict[str, str]         # conference -> champion when its tournament is over
    n_national_seeds: int = 16
    rpi_weights: RpiWeights = field(default_factory=RpiWeights)


@dataclass
class SimParams:
    simulations: int
    seed: int
    win_prob: Callable[[float], float]     # P(win) for a rating difference (incl. home edge)
    selection_score: Callable[[float, float, float], float]   # (rpi_rank, rating_rank, win_pct)
    host_score: Callable[[float, float, float], float]
    committee_noise: float                 # scale of logistic noise added to both scores
    min_at_large_win_pct: float
    field_size: int = 64
    hosts: int = 16
    conf_tourney_home: float = 0.0         # home edge share for the top seed in conf tourneys
    keep_conference_apart: bool = True


class Tally:
    def __init__(self):
        self.c: dict[str, Counter] = defaultdict(Counter)
        self.wins: dict[str, list[int]] = defaultdict(list)
        self.losses: dict[str, list[int]] = defaultdict(list)
        self.reg_wins: dict[str, list[int]] = defaultdict(list)
        self.reg_losses: dict[str, list[int]] = defaultdict(list)
        self.conf_wins: dict[str, list[int]] = defaultdict(list)
        self.conf_losses: dict[str, list[int]] = defaultdict(list)
        self.seed_line: dict[str, list[int]] = defaultdict(list)
        self.rpi_rank: dict[str, list[int]] = defaultdict(list)
        self.n = 0


class Simulator:
    def __init__(self, si: SimInputs, sp: SimParams):
        self.si, self.sp = si, sp
        n = int(2 * DIFF_LIMIT / DIFF_STEP) + 1
        self.table = [sp.win_prob(-DIFF_LIMIT + i * DIFF_STEP) for i in range(n)]
        for v in self.table[:: max(n // 50, 1)]:
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"win_probability returned {v!r}; it must be a probability in [0, 1]")
        self.conf_of = {t: v["conference"] for t, v in si.teams.items()}
        self.members: dict[str, list[str]] = defaultdict(list)
        for t, c in self.conf_of.items():
            self.members[c].append(t)
        self.results0 = [(g.home, g.away, 1.0 if g.margin > 0 else 0.0 if g.margin < 0 else 0.5, g.neutral)
                         for g in si.completed]
        self.rpi_state = RpiState(self.results0, si.rpi_weights)
        self.base_w, self.base_l = Counter(), Counter()
        self.base_cw, self.base_cl = Counter(), Counter()
        self.base_h2h = Counter()  # (a, b) -> conference wins of a over b
        for g in si.completed:
            if g.margin == 0:
                continue
            w, l = (g.home, g.away) if g.margin > 0 else (g.away, g.home)
            self.base_w[w] += 1
            self.base_l[l] += 1
            if g.game_type == "R" and g.conf_game:
                self.base_cw[w] += 1
                self.base_cl[l] += 1
                self.base_h2h[(w, l)] += 1
        self.base_reg_w = Counter()
        self.base_reg_l = Counter()
        for g in si.completed:
            if g.game_type == "R" and g.margin:
                w, l = (g.home, g.away) if g.margin > 0 else (g.away, g.home)
                self.base_reg_w[w] += 1
                self.base_reg_l[l] += 1

    # --- single game -------------------------------------------------------------
    def p_win(self, d: float) -> float:
        i = int(round((min(max(d, -DIFF_LIMIT), DIFF_LIMIT) + DIFF_LIMIT) / DIFF_STEP))
        return self.table[i]

    def play(self, rng: random.Random, a: str, b: str, home: float, R: dict[str, float], log: list) -> str:
        """Neutral/home game in weekend mode; home = +1 a at home, -1 b at home, 0 neutral."""
        d = R[a] - R[b] + home * self.si.home_edge
        w = a if rng.random() < self.p_win(d) else b
        log.append((a, b, w, home == 0))
        return w

    def series(self, rng, a, b, R, log, best_of=3, home=0.0) -> str:
        need, wa, wb = best_of // 2 + 1, 0, 0
        while wa < need and wb < need:
            if self.play(rng, a, b, home, R, log) == a:
                wa += 1
            else:
                wb += 1
        return a if wa == need else b

    def double_elim(self, rng, seeds: list[str], R, log, final: str = "if_necessary",
                    home_team: str | None = None) -> str:
        """Generic double elimination by loss count; pairs top-v-bottom within a loss group.
        final='single': once two teams remain they play one game."""
        losses = {t: 0 for t in seeds}
        order = {t: i for i, t in enumerate(seeds)}
        alive = list(seeds)
        while len(alive) > 1:
            if len(alive) == 2 and final == "single":
                return self._g(rng, alive[0], alive[1], R, log, home_team)
            groups = [sorted((t for t in alive if losses[t] == k), key=order.get) for k in (0, 1)]
            pairs = []
            if len(groups[0]) == 1 and len(groups[1]) == 1:
                pairs = [(groups[0][0], groups[1][0])]
            else:
                for grp in groups:
                    g = list(grp)
                    if len(g) % 2 == 1:
                        g = g[1:]  # top team in an odd group waits
                    for i in range(len(g) // 2):
                        pairs.append((g[i], g[-1 - i]))
            if not pairs:
                pairs = [(groups[0][0], groups[1][0])]
            for a, b in pairs:
                w = self._g(rng, a, b, R, log, home_team)
                loser = b if w == a else a
                losses[loser] += 1
            alive = [t for t in alive if losses[t] < 2]
        return alive[0]

    def _g(self, rng, a, b, R, log, home_team):
        home = 1.0 if a == home_team else -1.0 if b == home_team else 0.0
        return self.play(rng, a, b, home, R, log)

    def single_elim(self, rng, seeds: list[str], R, log, byes: int = 0, final: str = "single") -> str:
        n = len(seeds)
        if n == 1:
            return seeds[0]
        size = 1 << (n - 1).bit_length()
        if byes > size - n and byes * 2 < n:
            # staggered byes: seeds 1..byes enter last, byes+1..2*byes one round earlier
            top, mid, rest = seeds[:byes], seeds[byes:2 * byes], seeds[2 * byes:]
            while len(rest) > byes:
                rest = self._round(rng, rest, R, log, len(rest) - byes)
            field = top + self._round(rng, mid + rest, R, log, byes) if len(mid + rest) > byes else top + mid + rest
            return self.single_elim(rng, field, R, log, 0, final)
        order = self._bracket(size)
        slots = [seeds[s - 1] if s <= n else None for s in order]
        while len(slots) > 1:
            nxt = []
            for i in range(0, len(slots), 2):
                a, b = slots[i], slots[i + 1]
                if a is None or b is None:
                    nxt.append(a or b)
                elif len(slots) == 2 and final == "best_of_3":
                    nxt.append(self.series(rng, a, b, R, log))
                else:
                    nxt.append(self.play(rng, a, b, 0.0, R, log))
            slots = nxt
        return slots[0]

    def _round(self, rng, teams, R, log, games: int) -> list[str]:
        """Bottom 2*games teams play high-v-low; returns survivors in seed order."""
        keep, play = teams[:len(teams) - 2 * games], teams[len(teams) - 2 * games:]
        winners = [self.play(rng, play[i], play[-1 - i], 0.0, R, log) for i in range(games)]
        pos = {t: i for i, t in enumerate(teams)}
        return sorted(keep + winners, key=pos.get)

    @staticmethod
    def _bracket(size: int) -> list[int]:
        order = [1]
        while len(order) < size:
            m = 2 * len(order) + 1
            order = [x for s in order for x in (s, m - s)]
        return order

    def round_robin(self, rng, teams, R, log) -> str:
        w = Counter()
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                w[self.play(rng, teams[i], teams[j], 0.0, R, log)] += 1
        best = max(w[t] for t in teams)
        return rng.choice([t for t in teams if w[t] == best])

    def conference_tournament(self, rng, fmt: dict, seeds: list[str], R, log) -> str | None:
        kind = fmt.get("format", "double_elim")
        n = min(int(fmt.get("teams") or 0), len(seeds))
        if kind == "none" or n < 2:
            return None
        field_ = seeds[:n]
        final = fmt.get("final", "single")
        if kind == "series":
            return self.series(rng, field_[0], field_[1], R, log, 3)
        if kind == "single_elim":
            return self.single_elim(rng, field_, R, log, int(fmt.get("byes") or 0), final)
        if kind in ("pods", "pool_play"):
            k = max(int(fmt.get("pods") or 2), 1)
            pods: list[list[str]] = [[] for _ in range(k)]
            for i, t in enumerate(field_):
                rnd, pos = divmod(i, k)
                pods[pos if rnd % 2 == 0 else k - 1 - pos].append(t)
            pod_format = fmt.get("pod_format", "double_elim" if kind == "pods" else "round_robin")
            winners = [self.round_robin(rng, p, R, log) if pod_format == "round_robin"
                       else self.double_elim(rng, p, R, log) for p in pods if p]
            if len(winners) == 2 and final == "best_of_3":
                return self.series(rng, winners[0], winners[1], R, log, 3)
            return self.single_elim(rng, winners, R, log)
        # double elimination; opening single-elimination round for non-bye seeds
        byes = int(fmt.get("byes") or 0)
        if 0 < byes < n:
            rest = field_[byes:]
            games = len(rest) // 2
            field_ = field_[:byes] + self._round(rng, rest, R, log, games)
        return self.double_elim(rng, field_, R, log, "single" if final == "single" else "if_necessary",
                                home_team=field_[0] if self.sp.conf_tourney_home else None)

    # --- one season ---------------------------------------------------------------
    def run(self) -> Tally:
        si, sp = self.si, self.sp
        rng = random.Random(sp.seed)
        tally = Tally()
        teams = list(si.teams)
        base_rank = ranks(si.rating)
        for _ in range(sp.simulations):
            R = {t: si.rating.get(t, 0.0) + rng.gauss(0.0, si.rating_sd.get(t, 0.0)) for t in teams}
            W, L = Counter(self.base_w), Counter(self.base_l)
            CW, CL = Counter(self.base_cw), Counter(self.base_cl)
            RW, RL = Counter(self.base_reg_w), Counter(self.base_reg_l)
            H2H = Counter(self.base_h2h)
            extra = []
            for g, mid in si.remaining:
                d = R[g.home] - R[g.away] + (0.0 if g.neutral else si.home_edge)
                if mid:
                    d += si.midweek.get(g.home, 0.0) - si.midweek.get(g.away, 0.0)
                hw = rng.random() < self.p_win(d)
                w, l = (g.home, g.away) if hw else (g.away, g.home)
                W[w] += 1
                L[l] += 1
                RW[w] += 1
                RL[l] += 1
                if g.conf_game:
                    CW[w] += 1
                    CL[l] += 1
                    H2H[(w, l)] += 1
                extra.append((g.home, g.away, 1.0 if hw else 0.0, g.neutral))
            for t in teams:
                tally.reg_wins[t].append(RW[t])
                tally.reg_losses[t].append(RL[t])
                tally.conf_wins[t].append(CW[t])
                tally.conf_losses[t].append(CL[t])
            # conference standings, tournaments, automatic bids
            auto: dict[str, str] = {}
            post_log: list = []
            for conf, mem in self.members.items():
                if conf == "Independent" or conf not in si.formats:
                    continue
                pct = {t: (CW[t] + 0.5) / (CW[t] + CL[t] + 1.0) for t in mem}
                tieb = {t: rng.random() for t in mem}
                h2h = {t: sum(H2H[(t, o)] - H2H[(o, t)] for o in mem if pct[o] == pct[t] and o != t) for t in mem}
                seeds = sorted(mem, key=lambda t: (-pct[t], -h2h[t], tieb[t]))
                best = pct[seeds[0]]
                for t in mem:
                    if pct[t] == best:
                        tally.c[t]["reg_title"] += 1
                fmt = si.formats[conf]
                if conf in si.done_champions:
                    champ = si.done_champions[conf]
                else:
                    champ = self.conference_tournament(rng, fmt, seeds, R, post_log)
                if champ:
                    tally.c[champ]["conf_tourney"] += 1
                if fmt.get("auto_bid") == "none":
                    continue
                aq = seeds[0] if (fmt.get("auto_bid") == "regular_season" or not champ) else champ
                auto[conf] = aq
            for a, b, w, neutral in post_log:
                l = b if w == a else a
                W[w] += 1
                L[l] += 1
                extra.append((a, b, 1.0 if w == a else 0.0, True))
            # selection
            rp = self.rpi_state.compute(extra)
            rk = ranks(rp)
            rr = ranks(R)
            for t in teams:
                tally.rpi_rank[t].append(rk.get(t, len(rk)))
            noise = {t: self._logistic(rng) * sp.committee_noise for t in teams}
            wpct = {t: W[t] / (W[t] + L[t]) if W[t] + L[t] else 0.0 for t in teams}
            # teams outside the RPI top SEL_POOL_RPI are never at-large candidates (speed)
            sel = {t: sp.selection_score(rk.get(t, 999), rr[t], wpct[t]) + noise[t] if rk.get(t, 999) <= SEL_POOL_RPI
                   else -1e9 for t in teams}
            aq_set = set(auto.values())
            n_at_large = sp.field_size - len(aq_set)
            pool = sorted((t for t in teams if t not in aq_set and wpct[t] >= sp.min_at_large_win_pct),
                          key=lambda t: -sel[t])
            if len(pool) < n_at_large:  # not enough eligible teams: relax the win % rule
                pool += sorted((t for t in teams if t not in aq_set and t not in pool), key=lambda t: -sel[t])
            field_ = sorted(aq_set) + pool[:n_at_large]  # sorted: set order varies by hash seed
            hsc = {t: sp.host_score(rk.get(t, 999), rr[t], wpct[t]) + noise[t] for t in field_}
            hosts = sorted(field_, key=lambda t: -hsc[t])[:sp.hosts]
            others = sorted((t for t in field_ if t not in hosts), key=lambda t: -sel[t])
            for t in aq_set:
                tally.c[t]["auto_bid"] += 1
            for t in field_:
                tally.c[t]["bid"] += 1
            for i, t in enumerate(hosts):
                tally.c[t]["host"] += 1
                if i < si.n_national_seeds:
                    tally.c[t]["national_seed"] += 1
                tally.seed_line[t].append(1)
            regionals = self.place(hosts, others)
            for k, reg in enumerate(regionals):
                for line, t in enumerate(reg[1:], start=2):
                    tally.seed_line[t].append(line)
            # NCAA tournament
            ncaa_log: list = []
            reg_w = [self.double_elim(rng, reg, R, ncaa_log, home_team=reg[0]) for reg in regionals]
            for t in reg_w:
                tally.c[t]["regional"] += 1
            pos = {k + 1: w for k, w in enumerate(reg_w)}  # by national-seed slot
            cws = {}
            for k in range(1, 9):
                a, b = pos[k], pos[17 - k]
                home = a if a == regionals[k - 1][0] else b if b == regionals[16 - k][0] else a
                other = b if home == a else a
                w = self.series(rng, home, other, R, ncaa_log, 3, home=1.0)
                cws[k] = cws[17 - k] = w
                tally.c[w]["super"] += 1
            finalists = []
            for slots in CWS_BRACKETS:
                teams_b = []
                for s in slots:
                    if cws[s] not in teams_b:
                        teams_b.append(cws[s])
                finalists.append(self.double_elim(rng, teams_b, R, ncaa_log))
            for t in finalists:
                tally.c[t]["finals"] += 1
            champ = self.series(rng, finalists[0], finalists[1], R, ncaa_log, 3)
            tally.c[champ]["title"] += 1
            for a, b, w, _n in ncaa_log:
                l = b if w == a else a
                W[w] += 1
                L[l] += 1
            for t in teams:
                tally.wins[t].append(W[t])
                tally.losses[t].append(L[t])
            tally.n += 1
        tally.base_rank = base_rank  # type: ignore[attr-defined]
        return tally

    @staticmethod
    def _logistic(rng: random.Random) -> float:
        u = min(max(rng.random(), 1e-12), 1 - 1e-12)
        return math.log(u / (1 - u))

    def place(self, hosts: list[str], others: list[str]) -> list[list[str]]:
        """Regionals by S-curve: national seed k gets 2-seed 33-k, 3-seed 32+k, 4-seed 65-k
        (overall ranks); then conference-mates are swapped apart within each seed line."""
        regs = [[h] for h in hosts]
        lines = [others[0:16], others[16:32], others[32:48]]
        for li, line in enumerate(lines):
            order = list(reversed(line)) if li in (0, 2) else list(line)
            for k, t in enumerate(order[:len(regs)]):
                regs[k].append(t)
        if self.sp.keep_conference_apart:
            for li in (1, 2, 3):
                for k in range(len(regs)):
                    if len(regs[k]) <= li:
                        continue
                    t = regs[k][li]
                    if self._clash(t, regs[k][:li] + regs[k][li + 1:]):
                        for step in range(1, len(regs)):
                            for j in (k + step, k - step):
                                if 0 <= j < len(regs) and len(regs[j]) > li:
                                    u = regs[j][li]
                                    if not self._clash(u, regs[k][:li] + regs[k][li + 1:]) and \
                                            not self._clash(t, regs[j][:li] + regs[j][li + 1:]):
                                        regs[k][li], regs[j][li] = u, t
                                        break
                            else:
                                continue
                            break
        return regs

    def _clash(self, t: str, others: list[str]) -> bool:
        c = self.conf_of.get(t)
        return c not in (None, "Independent") and any(self.conf_of.get(o) == c for o in others)


def quantile(xs: list[int], q: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    i = min(max(int(round(q * (len(s) - 1))), 0), len(s) - 1)
    return float(s[i])
