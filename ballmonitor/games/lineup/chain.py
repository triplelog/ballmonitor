"""Exact expected runs per game for a batting order (a Markov chain over bases and outs).

A plate appearance ends in one of OUTCOMES, with the hitter's own rates. Runners move by the
fixed league-average rates in rules.toml (`transitions`). An inning is followed state by
state (24 = 3 outs x 8 base combinations) until three outs, so the expected runs and who
leads off the next inning come out exactly: no random draws. A game is 9 innings; the
lineup turns over from inning to inning.

`expected_runs(order, rates)` scores one order (web/game.js does the same steps in the same
order). `all_orders(rates)` scores all 9! = 362,880 orders at once with numpy (one inning per
batting sequence, shared by every order that contains it as a rotation).
"""

from __future__ import annotations

import itertools
import math
import tomllib
from pathlib import Path

RULES_FILE = Path(__file__).parent / "rules.toml"
OUTCOMES = ("K", "BB", "1B", "2B", "3B", "HR", "OUT")   # BB = walks + hit by pitch; OUT = out in play
N_STATES = 24                                         # outs * 8 + bases (bit 1 = 1st, 2 = 2nd, 4 = 3rd)


def load_rules(path: Path = RULES_FILE) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _walk(bases: int) -> tuple[int, int]:
    """Forced advance only: (new bases, runs)."""
    if not bases & 1:
        return bases | 1, 0
    if not bases & 2:
        return bases | 3, 0
    if not bases & 4:
        return 7, 0
    return 7, 1


def transitions(adv: dict) -> dict[tuple[int, int, str], list[tuple[float, int, int, int]]]:
    """(outs, bases, outcome) -> [(probability, new outs, new bases, runs)]; new outs 3 = inning over."""
    out = {}
    for outs in range(3):
        for bases in range(8):
            on1, on2, on3 = bases & 1, bases & 2, bases & 4
            for o in OUTCOMES:
                res: list[tuple[float, int, int, int]] = []
                if o == "K":
                    res = [(1.0, outs + 1, bases, 0)]
                elif o == "BB":
                    nb, r = _walk(bases)
                    res = [(1.0, outs, nb, r)]
                elif o == "HR":
                    res = [(1.0, outs, 0, 1 + bin(bases).count("1"))]
                elif o == "3B":
                    res = [(1.0, outs, 4, bin(bases).count("1"))]
                elif o == "2B":
                    runs = (1 if on2 else 0) + (1 if on3 else 0)
                    if on1:
                        p = adv["first_scores_on_double"]
                        res = [(p, outs, 2, runs + 1), (1 - p, outs, 6, runs)]
                    else:
                        res = [(1.0, outs, 2, runs)]
                elif o == "1B":
                    # lead runner first: 3rd scores; 2nd scores or stops at 3rd; 1st takes 3rd only if open
                    runs = 1 if on3 else 0
                    for p2, scored2 in (((adv["second_scores_on_single"], True), (1 - adv["second_scores_on_single"], False))
                                        if on2 else ((1.0, None),)):
                        third_open = not (on2 and not scored2)
                        r = runs + (1 if scored2 else 0)
                        nb = 1 | (4 if on2 and not scored2 else 0)
                        if on1:
                            p13 = adv["first_to_third_on_single"] if third_open else 0.0
                            if p13:
                                res.append((p2 * p13, outs, nb | 4, r))
                            res.append((p2 * (1 - p13), outs, nb | 2, r))
                        else:
                            res.append((p2, outs, nb, r))
                elif o == "OUT":
                    if outs == 2:
                        res = [(1.0, 3, bases, 0)]
                    else:
                        dp = adv["double_play"] if on1 else 0.0
                        if dp:
                            res.append((dp, outs + 2, bases & ~1, 0))   # others hold (inning over at 1 out)
                        rest = 1 - dp
                        p3 = adv["third_scores_on_out"] if on3 else 0.0
                        for a3, scored3 in ((p3, True), (1 - p3, False)) if on3 else ((1.0, False),):
                            third_free = not on3 or scored3
                            p2 = adv["second_to_third_on_out"] if on2 and third_free else 0.0
                            for a2, moved2 in ((p2, True), (1 - p2, False)) if p2 else ((1.0, False),):
                                nb = (4 if (on3 and not scored3) or moved2 else 0) | (2 if on2 and not moved2 else 0)
                                second_free = not nb & 2
                                p1 = adv["first_to_second_on_out"] if on1 and second_free else 0.0
                                for a1, moved1 in ((p1, True), (1 - p1, False)) if p1 else ((1.0, False),):
                                    b = nb | (2 if moved1 else (1 if on1 else 0))
                                    res.append((rest * a3 * a2 * a1, outs + 1, b, 1 if scored3 else 0))
                out[(outs, bases, o)] = [t for t in res if t[0] > 0]
    return out


def batter_tables(rates: list[float], trans) -> tuple[list[list[float]], list[float], list[float]]:
    """One hitter's 24x24 move matrix T, expected runs R and chance the inning ends X, per state."""
    T = [[0.0] * N_STATES for _ in range(N_STATES)]
    R, X = [0.0] * N_STATES, [0.0] * N_STATES
    for outs in range(3):
        for bases in range(8):
            s = outs * 8 + bases
            for o, p in zip(OUTCOMES, rates):
                for q, no, nb, runs in trans[(outs, bases, o)]:
                    R[s] += p * q * runs
                    if no >= 3:
                        X[s] += p * q
                    else:
                        T[s][no * 8 + nb] += p * q
    return T, R, X


def expected_runs(order: list[int], rates: list[list[float]], rules: dict | None = None) -> float:
    """Expected runs per game for `order` (lineup slot -> hitter index into `rates`)."""
    rules = rules or load_rules()
    trans = transitions(rules["advance"])
    tables = [batter_tables(r, trans) for r in rates]
    innings, depth = rules["game"]["innings"], rules["game"]["max_batters_per_inning"]
    n = len(order)
    inning = []                    # per leadoff slot: (expected runs, P(next inning's leadoff slot))
    for s in range(n):
        v = [0.0] * N_STATES
        v[0] = 1.0
        runs, nxt = 0.0, [0.0] * n
        for k in range(depth):
            T, R, X = tables[order[(s + k) % n]]
            runs += sum(a * b for a, b in zip(v, R))
            nxt[(s + k + 1) % n] += sum(a * b for a, b in zip(v, X))
            v = [sum(v[i] * T[i][j] for i in range(N_STATES)) for j in range(N_STATES)]
        inning.append((runs, nxt))
    lead, total = [1.0] + [0.0] * (n - 1), 0.0
    for _ in range(innings):
        total += sum(lead[s] * inning[s][0] for s in range(n))
        new = [0.0] * n
        for s in range(n):
            for j in range(n):
                new[j] += lead[s] * inning[s][1][j]
        lead = new
    return total


def _lehmer_rank(seqs):
    """Index of each permutation (rows of `seqs`) in itertools.permutations(range(n)) order."""
    import numpy as np

    n = seqs.shape[1]
    rank = np.zeros(len(seqs), dtype=np.int64)
    for i in range(n):
        smaller_later = (seqs[:, i + 1:] < seqs[:, i:i + 1]).sum(axis=1)
        rank += smaller_later * math.factorial(n - 1 - i)
    return rank


def all_orders(rates: list[list[float]], rules: dict | None = None):
    """Expected runs per game for every order: (orders (9!, 9) int8, runs (9!,) float64), with
    orders in itertools.permutations order. Same arithmetic as expected_runs."""
    import numpy as np

    rules = rules or load_rules()
    trans = transitions(rules["advance"])
    n = len(rates)
    tabs = [batter_tables(r, trans) for r in rates]
    T = [np.array(t[0]) for t in tabs]
    R = [np.array(t[1]) for t in tabs]
    X = [np.array(t[2]) for t in tabs]
    seqs = np.array(list(itertools.permutations(range(n))), dtype=np.int8)
    m = len(seqs)
    depth, innings = rules["game"]["max_batters_per_inning"], rules["game"]["innings"]

    # 1. one inning for every batting sequence (each permutation, led off by its first hitter)
    rows_for = [[np.flatnonzero(seqs[:, c] == b) for b in range(n)] for c in range(n)]
    v = np.zeros((m, N_STATES))
    v[:, 0] = 1.0
    E = np.zeros(m)
    D = np.zeros((m, n))           # D[q, j]: next inning is led off by the hitter at offset j of sequence q
    for k in range(depth):
        c = k % n
        for b in range(n):
            rows = rows_for[c][b]
            vb = v[rows]
            E[rows] += vb @ R[b]
            D[rows, (k + 1) % n] += vb @ X[b]
            v[rows] = vb @ T[b]

    # 2. a game: each order's rotations are sequences; chain nine innings over the leadoff slot
    total = np.zeros(m)
    lead = np.zeros((m, n))
    lead[:, 0] = 1.0
    rot = [_lehmer_rank(np.roll(seqs, -s, axis=1)) for s in range(n)]   # order rotated to start at slot s
    for _ in range(innings):
        new = np.zeros((m, n))
        for s in range(n):
            q = rot[s]
            total += lead[:, s] * E[q]
            for j in range(n):
                new[:, (s + j) % n] += lead[:, s] * D[q, j]
        lead = new
    return seqs, total
