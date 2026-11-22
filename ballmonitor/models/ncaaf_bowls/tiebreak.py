"""Conference standings with tiebreakers: who plays in each conference title game.

The common FBS procedure (the ACC, Big Ten, Big 12 and SEC publish nearly the same steps, and
most other conferences follow them), applied to teams level on conference win percentage:

Two teams tied
  1. Head-to-head result.
  2. Win percentage against the conference opponents both teams played (common opponents).
  3. Rating (a stand-in for the later steps: record against the next-best common opponent,
     opponents' combined win percentage and the computer-ranking composites the conferences
     use; the simulator does not track those). Then a coin flip.

Three or more teams tied
  1. Combined head-to-head win percentage among the tied teams, if every tied team played
     every other. If not, a team that beat all the others goes first, and a team that lost to
     all the others drops out of the tie.
  2. Win percentage against the conference opponents all the tied teams played.
  3. Rating, then a coin flip.

As soon as a step separates the teams, the leaders are re-broken from step 1 (the two-team
steps when two are left). Once the top team is set, the rest of the tie starts again from
step 1 (every conference's rule: "the remaining teams revert to the beginning").

Simplifications: only conference games count, and step 3 uses the published rating. A
conference with divisions ranks each division on its own (`opponents` = the whole conference,
so cross-division opponents count as common opponents); simulator.py does that.
"""

from __future__ import annotations

import random
from typing import Iterable, Mapping, Sequence


def _pct(wins: int, losses: int) -> float | None:
    return wins / (wins + losses) if wins + losses else None


def _head_to_head(group: list[str], beat: Mapping[tuple[str, str], int]) -> list[str]:
    """Step 1: the leaders of `group` by head-to-head, or `group` unchanged if it doesn't split."""
    if len(group) == 2:
        a, b = group
        wa, wb = beat.get((a, b), 0), beat.get((b, a), 0)
        return group if wa == wb else [a if wa > wb else b]
    played = lambda x, y: beat.get((x, y), 0) + beat.get((y, x), 0) > 0  # noqa: E731
    others = {t: [o for o in group if o != t] for t in group}
    if all(played(t, o) for t in group for o in others[t]):
        # round robin: combined win percentage among the tied teams
        score = {t: _pct(sum(beat.get((t, o), 0) for o in others[t]),
                         sum(beat.get((o, t), 0) for o in others[t])) for t in group}
        best = max(score.values())
        return [t for t in group if score[t] == best]
    # not a round robin: a team that beat every other tied team goes first ...
    sweep = [t for t in group if all(beat.get((t, o), 0) > beat.get((o, t), 0) for o in others[t])]
    if sweep:
        return sweep[:1]
    # ... and a team that lost to every other tied team drops out
    swept = {t for t in group if all(beat.get((o, t), 0) > beat.get((t, o), 0) for o in others[t])}
    rest = [t for t in group if t not in swept]
    return rest if rest else group


def _common_opponents(group: list[str], members: Iterable[str],
                      beat: Mapping[tuple[str, str], int]) -> list[str]:
    """Step 2: the leaders by win percentage against the opponents every tied team played."""
    tied = set(group)
    common = [o for o in members if o not in tied
              and all(beat.get((t, o), 0) + beat.get((o, t), 0) > 0 for t in group)]
    if not common:
        return group
    score = {t: _pct(sum(beat.get((t, o), 0) for o in common), sum(beat.get((o, t), 0) for o in common))
             for t in group}
    best = max(score.values())
    return [t for t in group if score[t] == best]


def _top(group: list[str], members: Sequence[str], beat: Mapping[tuple[str, str], int],
         rating: Mapping[str, float], rng: random.Random | None) -> str:
    """The team that wins the tie among `group` (all level on conference win percentage)."""
    while len(group) > 1:
        for step in (lambda g: _head_to_head(g, beat), lambda g: _common_opponents(g, members, beat)):
            leaders = step(group)
            if len(leaders) < len(group):
                group = leaders
                break   # re-break the smaller group from step 1
        else:
            best = max(rating.get(t, 0.0) for t in group)
            top = [t for t in group if rating.get(t, 0.0) == best]
            return top[0] if len(top) == 1 or rng is None else rng.choice(top)
    return group[0]


def rank_standings(
    members: Sequence[str],
    conf_pct: Mapping[str, float],
    beat: Mapping[tuple[str, str], int],
    rating: Mapping[str, float],
    rng: random.Random | None = None,
    places: int | None = None,
    opponents: Sequence[str] | None = None,
) -> list[str]:
    """Conference standings, best first: by conference win percentage, ties broken as in the
    module docstring.

    members   the conference's teams (ids)
    conf_pct  each team's conference win percentage
    beat      (winner, loser) -> number of conference games the winner won against the loser
    rating    the rating step 3 falls back on (the published rating)
    rng       coin flip for teams level on everything (else the first listed wins)
    places    stop after this many places (2 = the title game)
    opponents the teams whose games count as common opponents (default `members`; the whole
              conference when `members` is one division)"""
    pool = members if opponents is None else opponents
    order: list[str] = []
    want = len(members) if places is None else min(places, len(members))
    for pct in sorted({conf_pct[t] for t in members}, reverse=True):
        tied = [t for t in members if conf_pct[t] == pct]
        while tied and len(order) < want:
            top = _top(tied, pool, beat, rating, rng)
            order.append(top)
            tied = [t for t in tied if t != top]
        if len(order) >= want:
            break
    return order
