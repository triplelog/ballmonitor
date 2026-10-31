"""Ranked-ballot voting methods (stdlib only).

A ballot is a list of candidate ids, best first. Ballots are truncated (a voter ranks 3, 5,
10 or 25 names out of many); a candidate a voter left off is treated as ranked below every
candidate on that ballot and tied with the other unranked ones (`unranked = "below"`), or the
ballot says nothing about pairs involving an unranked candidate (`unranked = "ignore"`).

Every method returns a full order of the candidates (not just a winner) so a poll like the
AP Top 25 can be re-ranked. Ties are broken by `tiebreak`, a dict candidate -> sortable key
(larger = better), the same for every method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

Ballot = list[str]


@dataclass
class Result:
    order: list[str]                       # best first, every candidate
    scores: dict[str, float]               # the number the method ranks by (see score_label)
    score_label: str
    log: list[str] = field(default_factory=list)   # round-by-round notes for the steps
    exact: bool = True                     # False if a heuristic was used (Kemeny local search)


def candidates_of(ballots: list[Ballot]) -> list[str]:
    seen: dict[str, None] = {}
    for b in ballots:
        for c in b:
            seen.setdefault(c, None)
    return list(seen)


def _sorted(cands, key: Callable[[str], tuple], tiebreak: dict[str, tuple]) -> list[str]:
    return sorted(cands, key=lambda c: (key(c), tiebreak.get(c, ()), c), reverse=True)


# ---- positional --------------------------------------------------------------------------

def positional(ballots: list[Ballot], cands: list[str], points: Callable[[int, int], float],
               tiebreak: dict[str, tuple], label: str = "points") -> Result:
    """Sum of points by place: points(rank, ballot_length), rank 1 = top."""
    score = {c: 0.0 for c in cands}
    for b in ballots:
        for r, c in enumerate(b, 1):
            if c in score:
                score[c] += points(r, len(b))
    return Result(_sorted(cands, lambda c: (score[c],), tiebreak), score, label)


def place_counts(ballots: list[Ballot], cands: list[str], depth: int) -> dict[str, list[int]]:
    counts = {c: [0] * depth for c in cands}
    for b in ballots:
        for r, c in enumerate(b[:depth]):
            if c in counts:
                counts[c][r] += 1
    return counts


def plurality(ballots: list[Ballot], cands: list[str], tiebreak: dict[str, tuple]) -> Result:
    """First-place votes; ties broken by second-place votes, then third, … (a medal table)."""
    depth = max((len(b) for b in ballots), default=1)
    counts = place_counts(ballots, cands, depth)
    return Result(_sorted(cands, lambda c: tuple(counts[c]), tiebreak),
                  {c: float(counts[c][0]) for c in cands}, "first-place votes")


# ---- elimination methods -----------------------------------------------------------------

def _top(ballot: Ballot, alive: set[str]) -> str | None:
    for c in ballot:
        if c in alive:
            return c
    return None


def _irv_round(ballots, alive, tiebreak):
    """One IRV contest among `alive`: (winner, elimination order, log)."""
    alive = set(alive)
    eliminated, log = [], []
    while True:
        tally = {c: 0 for c in alive}
        active = 0
        for b in ballots:
            t = _top(b, alive)
            if t is not None:
                tally[t] += 1
                active += 1
        leader = max(alive, key=lambda c: (tally[c], tiebreak.get(c, ()), c))
        if len(alive) == 1 or tally[leader] * 2 > active:
            return leader, eliminated, log + [f"{leader} wins with {tally[leader]} of {active} active ballots"]
        loser = min(alive, key=lambda c: (tally[c], tiebreak.get(c, ()), c))
        log.append(f"out: {loser} ({tally[loser]} first choices, {active} active)")
        alive.discard(loser)
        eliminated.append(loser)


def _coombs_round(ballots, alive, tiebreak):
    """Coombs: majority of first choices wins, else drop the candidate with most last places.
    A ballot's remaining unranked candidates share its last place equally."""
    alive = set(alive)
    eliminated, log = [], []
    while True:
        tally = {c: 0 for c in alive}
        last = {c: 0.0 for c in alive}
        active = 0
        for b in ballots:
            ranked = [c for c in b if c in alive]
            if ranked:
                tally[ranked[0]] += 1
                active += 1
            unranked = alive.difference(ranked)
            if unranked:
                for c in unranked:
                    last[c] += 1.0 / len(unranked)
            elif ranked:
                last[ranked[-1]] += 1.0
        leader = max(alive, key=lambda c: (tally[c], tiebreak.get(c, ()), c))
        if len(alive) == 1 or tally[leader] * 2 > active:
            return leader, eliminated, log + [f"{leader} wins with {tally[leader]} of {active} first choices"]
        loser = max(alive, key=lambda c: (last[c], tuple(-x for x in tiebreak.get(c, ())), c))
        log.append(f"out: {loser} ({last[loser]:.1f} last places)")
        alive.discard(loser)
        eliminated.append(loser)


def _baldwin_round(ballots, alive, tiebreak):
    """Baldwin: repeatedly drop the lowest Borda score, recomputed among the remaining
    candidates (on each ballot the k remaining ranked names get k, k-1, …, 1; unranked 0)."""
    alive = set(alive)
    eliminated, log = [], []
    while len(alive) > 1:
        score = {c: 0 for c in alive}
        for b in ballots:
            ranked = [c for c in b if c in alive]
            for i, c in enumerate(ranked):
                score[c] += len(ranked) - i
        loser = min(alive, key=lambda c: (score[c], tiebreak.get(c, ()), c))
        log.append(f"out: {loser} (Borda {score[loser]})")
        alive.discard(loser)
        eliminated.append(loser)
    winner = next(iter(alive))
    return winner, eliminated, log + [f"{winner} is the last one left"]


def _bucklin_round(ballots, alive, tiebreak):
    """Bucklin: add 1st, then 2nd, … choices until someone is on more than half the ballots."""
    alive = set(alive)
    depth = max((len(b) for b in ballots), default=1)
    n = len(ballots)
    for r in range(1, depth + 1):
        tally = {c: 0 for c in alive}
        for b in ballots:
            for c in [c for c in b if c in alive][:r]:
                tally[c] += 1
        leader = max(alive, key=lambda c: (tally[c], tiebreak.get(c, ()), c))
        if tally[leader] * 2 > n or r == depth:
            rest = sorted(alive - {leader}, key=lambda c: (tally[c], tiebreak.get(c, ()), c))
            return leader, rest, [f"{leader} wins at depth {r} with {tally[leader]} of {n} ballots"]
    return max(alive, key=lambda c: (tiebreak.get(c, ()), c)), [], []


ROUNDS = {"irv": _irv_round, "coombs": _coombs_round, "baldwin": _baldwin_round, "bucklin": _bucklin_round}


def elimination(kind: str, ballots: list[Ballot], cands: list[str], tiebreak: dict[str, tuple],
                ordering: str = "sequential", positions: int = 0) -> Result:
    """Run an elimination method. ordering = "sequential": elect the winner, remove them and
    re-run for 2nd place, … (for the first `positions` places; the rest follow the last run's
    reverse elimination order). ordering = "elimination_order": one run; later eliminated =
    better."""
    run = ROUNDS[kind]
    alive = list(cands)
    order, log = [], []
    positions = positions or len(cands)
    while alive:
        winner, eliminated, rlog = run(ballots, alive, tiebreak)
        if not order:
            log = rlog
        if ordering == "elimination_order" or len(order) + 1 >= positions:
            order.append(winner)
            rest = [c for c in alive if c != winner]
            tail = [c for c in reversed(eliminated) if c in rest]
            order += tail + [c for c in _sorted(rest, lambda c: (), tiebreak) if c not in tail]
            break
        order.append(winner)
        alive = [c for c in alive if c != winner]
    n = len(order)
    return Result(order, {c: float(n - i) for i, c in enumerate(order)}, "place (reversed)", log)


# ---- pairwise (Condorcet) methods ---------------------------------------------------------

def pairwise(ballots: list[Ballot], cands: list[str], unranked: str = "below") -> dict[str, dict[str, int]]:
    """d[a][b] = number of ballots that rank a above b."""
    d = {a: {b: 0 for b in cands if b != a} for a in cands}
    cset = set(cands)
    for b in ballots:
        ranked = [c for c in b if c in cset]
        for i, a in enumerate(ranked):
            row = d[a]
            for c in ranked[i + 1:]:
                row[c] += 1
            if unranked == "below":
                for c in cset.difference(ranked):
                    row[c] += 1
    return d


def strength(d, a, b, measure: str) -> int:
    """How strongly a beats b (0 if it doesn't): margin or winning votes."""
    if d[a][b] <= d[b][a]:
        return 0
    return d[a][b] - d[b][a] if measure == "margin" else d[a][b]


def condorcet_winner(d, cands) -> str | None:
    for a in cands:
        if all(d[a][b] > d[b][a] for b in cands if b != a):
            return a
    return None


def condorcet_loser(d, cands) -> str | None:
    for a in cands:
        if all(d[a][b] < d[b][a] for b in cands if b != a):
            return a
    return None


def smith_set(d, cands, tiebreak) -> list[str]:
    """Smallest set whose members all beat everyone outside it (Copeland order, grown until closed)."""
    order = copeland(d, cands, tiebreak, 0.5).order
    for k in range(1, len(order) + 1):
        inner, outer = order[:k], order[k:]
        if all(d[a][b] > d[b][a] for a in inner for b in outer):
            return inner
    return order


def copeland(d, cands, tiebreak, tie_score: float = 0.5) -> Result:
    score = {a: sum(1.0 if d[a][b] > d[b][a] else tie_score if d[a][b] == d[b][a] else 0.0
                    for b in cands if b != a) for a in cands}
    return Result(_sorted(cands, lambda c: (score[c],), tiebreak), score, "pairwise wins")


def schulze(d, cands, tiebreak, measure: str = "winning_votes") -> Result:
    p = {a: {b: strength(d, a, b, measure) for b in cands if b != a} for a in cands}
    for k in cands:
        for i in cands:
            if i == k:
                continue
            pik = p[i][k]
            if not pik:
                continue
            row = p[i]
            for j in cands:
                if j != i and j != k:
                    v = min(pik, p[k][j])
                    if v > row[j]:
                        row[j] = v
    beats = {a: sum(1 for b in cands if b != a and p[a][b] > p[b][a]) for a in cands}
    return Result(_sorted(cands, lambda c: (beats[c],), tiebreak), {c: float(beats[c]) for c in cands},
                  "beats by strongest path")


def ranked_pairs(d, cands, tiebreak, measure: str = "winning_votes") -> Result:
    pairs = [(a, b) for a in cands for b in cands if a != b and d[a][b] > d[b][a]]
    pairs.sort(key=lambda ab: (strength(d, ab[0], ab[1], measure), -d[ab[1]][ab[0]],
                               tiebreak.get(ab[0], ()), ab[0]), reverse=True)
    locked: dict[str, set[str]] = {c: set() for c in cands}

    def reaches(x, y):
        stack, seen = [x], set()
        while stack:
            n = stack.pop()
            if n == y:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(locked[n])
        return False

    skipped = []
    for a, b in pairs:
        if reaches(b, a):
            skipped.append(f"{a}>{b}")
        else:
            locked[a].add(b)
    # topological order, ties among sources broken by tiebreak
    indeg = {c: 0 for c in cands}
    for a in cands:
        for b in locked[a]:
            indeg[b] += 1
    order, ready = [], [c for c in cands if indeg[c] == 0]
    while ready:
        ready = _sorted(ready, lambda c: (), tiebreak)
        c = ready.pop(0)
        order.append(c)
        for b in locked[c]:
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
    n = len(order)
    log = [f"{len(pairs)} majority pairs, {len(skipped)} skipped to avoid cycles"
           + (f" (strongest skipped: {skipped[0]})" if skipped else "")]
    return Result(order, {c: float(n - i) for i, c in enumerate(order)}, "place (reversed)", log)


def minimax(d, cands, tiebreak, measure: str = "margin") -> Result:
    worst = {a: max((strength(d, b, a, measure) for b in cands if b != a), default=0) for a in cands}
    return Result(_sorted(cands, lambda c: (-worst[c],), tiebreak), {c: float(worst[c]) for c in cands},
                  "worst defeat")


def kemeny_score(d, order) -> int:
    return sum(d[a][b] for i, a in enumerate(order) for b in order[i + 1:])


def kemeny(d, cands, tiebreak, exact_max: int = 10, start: list[str] | None = None) -> Result:
    """Order that agrees with the most (ballot, pair) preferences. Exact by dynamic programming
    over subsets for the first `exact_max` places of a starting order (rest fixed after it, then
    improved by local search); exact overall when there are at most `exact_max` candidates."""
    order = list(start or copeland(d, cands, tiebreak).order)
    exact = len(order) <= exact_max
    head = order[:exact_max]
    # DP: best[S] = best agreement for placing set S (as bitmask over head) at the top
    n = len(head)
    if n:
        best = {0: (0, ())}
        for mask in range(1, 1 << n):
            cand = None
            for i in range(n):
                if mask & (1 << i):
                    prev = best[mask ^ (1 << i)]
                    c = head[i]
                    gain = sum(d[head[j]][c] for j in range(n) if j != i and mask & (1 << j))
                    val = prev[0] + gain
                    key = (val, tiebreak.get(c, ()))
                    if cand is None or key > cand[0]:
                        cand = (key, prev[1] + (c,))
            best[mask] = (cand[0][0], cand[1])
        order = list(best[(1 << n) - 1][1]) + order[n:]
    # local search: move one candidate at a time to the spot that most improves agreement
    # (moving x past y changes agreement by d[y][x] - d[x][y]); repeat until no move helps
    if not exact:
        improved = True
        while improved:
            improved = False
            for x in list(order):
                i = order.index(x)
                best_gain, best_j, gain = 0, i, 0
                for j in range(i + 1, len(order)):            # move down
                    y = order[j]
                    gain += d[y][x] - d[x][y]
                    if gain > best_gain:
                        best_gain, best_j = gain, j
                gain = 0
                for j in range(i - 1, -1, -1):                # move up
                    y = order[j]
                    gain += d[x][y] - d[y][x]
                    if gain > best_gain:
                        best_gain, best_j = gain, j
                if best_gain > 0:
                    order.pop(i)
                    order.insert(best_j, x)
                    improved = True
    n_all = len(order)
    return Result(order, {c: float(n_all - i) for i, c in enumerate(order)}, "place (reversed)",
                  [f"agreement {kemeny_score(d, order)} (ballot-pair preferences honoured)"], exact)


# ---- comparing orders ---------------------------------------------------------------------

def footrule(ballot: Ballot, order: list[str], depth: int) -> int:
    """Spearman footrule between a truncated ballot and the top `depth` of an order; anything
    outside the top `depth` counts as place depth + 1."""
    pos_b = {c: i + 1 for i, c in enumerate(ballot[:depth])}
    pos_o = {c: i + 1 for i, c in enumerate(order[:depth])}
    return sum(abs(pos_b.get(c, depth + 1) - pos_o.get(c, depth + 1)) for c in set(pos_b) | set(pos_o))


def head_to_head(d, a, b) -> tuple[int, int]:
    return d[a][b], d[b][a]


def disagreements(orders: dict[str, list[str]], depth: int) -> dict[str, dict[str, int]]:
    """candidate -> {method: place} for every candidate in any method's top `depth`."""
    names = []
    for o in orders.values():
        for c in o[:depth]:
            if c not in names:
                names.append(c)
    return {c: {m: o.index(c) + 1 for m, o in orders.items()} for c in names}


__all__ = ["Result", "candidates_of", "positional", "plurality", "elimination", "pairwise", "copeland",
           "schulze", "ranked_pairs", "minimax", "kemeny", "condorcet_winner", "condorcet_loser",
           "smith_set", "footrule", "head_to_head", "disagreements", "place_counts"]
