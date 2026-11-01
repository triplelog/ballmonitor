"""Daily Triple Play puzzles: 3 categories, 17 players, one correct region each.

Regions (A, B, C = the three circles): ABC 1, AB/AC/BC 2 each, A/B/C-only 3 each,
outside 1 -> 17 players.

For each date (seeded by the date, so a rebuild reproduces the same puzzles):
1. difficulty from the weekday (FAME_FLOOR: who is famous enough to appear);
2. try random category triples (one team-type, one stat-type, one "trait" most of the time),
   rejecting pairs that are nearly the same set, pitcher-only + hitter-only mixes, triples
   used in the last REPEAT_DAYS days, or categories used yesterday;
3. the pool: players above the fame floor, active in 1910 or later, and not
   borderline for any of the three categories (Category.clear);
4. every region must have enough players; players are drawn by weight without
   replacement (no two with the same name), the outside player is a near miss when there
   is one (e.g. 380 homers for "400 career home runs");
5. players are weighted by fame x exp(CLOSE_BETA[level] x closeness): easy days favour
   clear-cut players, hard days close calls (barely in or barely out of a circle);
6. the best of the valid triples (by the chosen players' weights) is kept.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from itertools import combinations

from ballmonitor.games.triple_play.categories import CATEGORIES, Category

NEED = {"ABC": 1, "AB": 2, "AC": 2, "BC": 2, "A": 3, "B": 3, "C": 3, "": 1}             # 17 cards
NEED_BIG = {"ABC": 2, "AB": 3, "AC": 3, "BC": 3, "A": 4, "B": 4, "C": 4, "": 2}         # 25 cards (Sunday)
FAME_FLOOR = {"easy": 80.0, "medium": 62.0, "hard": 50.0, "big": 55.0}  # 2026-10-31: raised (was 55/32/24/30)
# how strongly each level favours close calls (closeness = how near a player is to a circle's
# line, Category.close): negative avoids them. Every level avoids them since 2026-10-31
# (was easy -2.5, medium 0.6, hard 1.8, big 0.8); harder days only allow a few more.
CLOSE_BETA = {"easy": -3.0, "medium": -2.0, "hard": -1.2, "big": -1.6}
# Mon = cities & states (MLB's traditional off day); Sunday = the big 25-card puzzle
WEEKDAY_LEVEL = ["medium", "easy", "medium", "medium", "hard", "hard", "big"]  # Mon..Sun
REPEAT_DAYS = 120
ATTEMPTS = 400
KEEP_BEST_OF = 6
STAT_KINDS = ("career", "season", "award")
TRAIT_KINDS = ("position", "bio", "award")


def region_of(p: dict, cats: list[Category]) -> str:
    return "".join(l for l, c in zip("ABC", cats) if c.test(p))


def compatible(cats: list[Category], members: dict[str, set]) -> bool:
    flags = {c.hitters for c in cats if c.hitters is not None}
    if len(flags) > 1:
        return False
    if sum(c.kind == "team" for c in cats) > 2 or sum(c.kind == "position" for c in cats) > 1:
        return False
    for a, b in combinations(cats, 2):
        sa, sb = members[a.id], members[b.id]
        if not sa or not sb:
            return False
        inter = len(sa & sb)
        if inter / min(len(sa), len(sb)) > 0.85 or inter / len(sa | sb) > 0.45:
            return False                     # nearly the same circle twice
        if {a.id, b.id} in ({"hr500", "hr400"}, {"w300", "w200"}, {"s_hr50", "s_hr40"},
                            {"born_dr", "born_intl"}, {"lefty_bat", "switch"}):
            return False
    return True


def pick_triple(rng: random.Random, by_kind: dict[str, list[Category]]) -> list[Category]:
    r = rng.random()
    if r < 0.55:      # team + stat + trait
        kinds = ["team", rng.choice(STAT_KINDS), rng.choice(TRAIT_KINDS)]
    elif r < 0.70:    # two teams + stat/trait
        kinds = ["team", "team", rng.choice(STAT_KINDS + TRAIT_KINDS)]
    elif r < 0.90:    # no team: stat + stat + trait
        kinds = [rng.choice(STAT_KINDS), rng.choice(STAT_KINDS), rng.choice(TRAIT_KINDS)]
    else:             # team + trait + trait
        kinds = ["team", rng.choice(TRAIT_KINDS), rng.choice(TRAIT_KINDS)]
    out: list[Category] = []
    for k in kinds:
        options = [c for c in by_kind[k] if c not in out]
        out.append(rng.choice(options))
    rng.shuffle(out)
    return out


def closeness(p: dict, cats: list[Category]) -> float:
    """0-1: the player's closest call among the three circles (mean of the top two)."""
    c = sorted((cat.close(p) for cat in cats), reverse=True)
    return (c[0] + c[1]) / 2


def draw(rng: random.Random, people: list[dict], n: int, used_names: set, weight) -> list[dict] | None:
    pool = [p for p in people if p["name"] not in used_names]
    chosen = []
    for _ in range(n):
        if not pool:
            return None
        weights = [weight(p) for p in pool]
        p = rng.choices(pool, weights=weights)[0]
        chosen.append(p)
        pool = [q for q in pool if q["name"] != p["name"]]
    return chosen


def build_puzzle(rng: random.Random, base: list[dict], pick, ok_triple, level: str, recent: list[set],
                 yesterday: set, card_extra=lambda p: {}, beta: float | None = None, need=None,
                 choose: str = "best") -> dict | None:
    """One puzzle from `base` (entities above the level's fame floor): `pick(rng)` proposes a
    category triple, `ok_triple(cats)` vets it. Shared by every pack."""
    beta = CLOSE_BETA[level] if beta is None else beta
    need = need or NEED
    candidates = []
    for _ in range(ATTEMPTS):
        cats = pick(rng)
        ids = {c.id for c in cats}
        if ids in recent or ids & yesterday or not ok_triple(cats):
            continue
        pool = [p for p in base if all(c.clear(p) for c in cats)]
        regions: dict[str, list] = {k: [] for k in need}
        for p in pool:
            regions[region_of(p, cats)].append(p)
        if any(len(regions[k]) < n + (1 if k in ("A", "B", "C") else 0) for k, n in need.items() if k):
            continue
        weight = lambda p: p["fame"] * math.exp(beta * closeness(p, cats))  # noqa: E731
        used, picks = set(), {}
        ok = True
        for k in ("ABC", "AB", "AC", "BC", "A", "B", "C"):
            got = draw(rng, regions[k], need[k], used, weight)
            if got is None:
                ok = False
                break
            picks[k] = got
            used |= {p["name"] for p in got}
        if not ok:
            continue
        outside = [p for p in regions[""] if p["name"] not in used]
        if not outside:
            continue
        # outside: a famous, clear non-member (never a near miss like 380 HR for "400 HR")
        scored = sorted(outside, key=lambda p: -p["fame"] * math.exp(-2 * max(c.near(p) for c in cats)))[:8]
        picks[""] = rng.sample(scored, min(need[""], len(scored)))
        if len(picks[""]) < need[""]:
            continue
        quality = sum(math.log(weight(p)) for ps in picks.values() for p in ps)
        candidates.append((quality, cats, picks))
        if len(candidates) >= KEEP_BEST_OF:
            break
    if not candidates:
        return None
    quality, cats, picks = max(candidates, key=lambda t: t[0]) if choose == "best" else rng.choice(candidates)
    cards = []
    for region, ps in picks.items():
        for p in ps:
            cards.append({"id": p["id"], "name": p["name"], **card_extra(p),
                          "region": region, "facts": [c.fact(p) for c in cats]})
    rng.shuffle(cards)
    return {"level": level, "need": need, "categories": [{"id": c.id, "label": c.label, "rule": c.rule} for c in cats],
            "cards": cards}


def baseball_maker(players: dict[str, dict]):
    """(day, level, recent, yesterday) -> puzzle, for the baseball pack."""
    members = {cid: {p["id"] for p in players.values() if p["fame"] >= FAME_FLOOR["hard"] and c.test(p)}
               for cid, c in CATEGORIES.items()}
    by_kind: dict[str, list[Category]] = {}
    for c in CATEGORIES.values():
        by_kind.setdefault(c.kind, []).append(c)
    bases = {lv: [p for p in players.values() if p["fame"] >= f and p["last"] >= 1910] for lv, f in FAME_FLOOR.items()}

    def make(day, level, recent, yesterday):
        rng = random.Random(f"triple-play-baseball-{day.isoformat()}")
        need = NEED_BIG if level == "big" else NEED
        for lv in dict.fromkeys((level, "medium", "hard")):   # fall back to a bigger pool if needed
            puzzle = build_puzzle(rng, bases[lv], lambda r: pick_triple(r, by_kind),
                                  lambda cats: compatible(cats, members), lv, recent, yesterday,
                                  card_extra=lambda p: {"sub": f"{p['first']}–{p['last']}"}, need=need)
            if puzzle:
                puzzle["pack"] = "baseball"
                return puzzle
        raise RuntimeError(f"no valid baseball puzzle for {day}")
    return make


def generate(players: dict[str, dict], start: dt.date, end: dt.date, log=print,
             places=None, places_weekday: int = 0) -> list[dict]:
    """The daily schedule: baseball every day, except `places_weekday` (0 = Monday, MLB's
    traditional off day) when a places maker is given. One numbering across both packs."""
    makers = {"baseball": baseball_maker(players)}
    if places is not None:
        makers["places"] = places
    out, history = [], {k: [] for k in makers}
    day, number = start, 1
    while day <= end:
        pack = "places" if "places" in makers and day.weekday() == places_weekday else "baseball"
        level = WEEKDAY_LEVEL[day.weekday()]
        hist = history[pack]
        recent = [h for d, h in hist if (day - d).days <= REPEAT_DAYS * (1 if pack == "baseball" else 3)]
        yesterday = hist[-1][1] if hist else set()
        puzzle = makers[pack](day, level, recent, yesterday)
        puzzle.update(date=day.isoformat(), number=number)
        out.append(puzzle)
        hist.append((day, {c["id"] for c in puzzle["categories"]}))
        day += dt.timedelta(days=1)
        number += 1
    log(f"generated {len(out)} puzzles {start} .. {end}")
    return out
