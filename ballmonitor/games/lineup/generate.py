"""Daily Lineup puzzles: nine real player-seasons, one per position; find the best batting order.

For each date (seeded by the date, so a rebuild reproduces it):
1. hitter types (KINDS) are dealt to the nine positions so the day mixes uneven profiles
   (TARGET: a star, a walk machine, two sluggers, a contact hitter, a singles hitter, two
   light hitters and one of anything); each position draws a season of its type, weighted by
   how well known the player is (square root of Triple Play's fame score, FAME_FLOOR and up). The DH can be a
   season from any position. DEALS deals are tried; the kept one is realistic (the nine's
   average on-base and slugging inside REALISTIC, the middle 80% of real team-seasons since
   1955), then has the most typed hitters, then is closest to a median team;
2. no player who appeared in the last REPEAT_DAYS days (a position with nobody left may reuse
   one; never the same player twice in a day);
3. all 9! orders are scored exactly (chain.all_orders); if the best order beats the worst by
   less than MIN_GAP runs per game the day is redrawn (up to TRIES times, keeping the widest);
4. the puzzle stores the nine hitters and their rates, the rules, the best and worst orders
   and the spread of all orders (percentiles), so the page can grade any order without a server.
"""

from __future__ import annotations

import datetime as dt
import random

import numpy as np

from ballmonitor.games.lineup import chain

FAME_FLOOR = 25.0       # ~670 players: enough that the repeat rule never runs dry (40 left ~360)
REPEAT_DAYS = 30
MIN_GAP = 0.13          # runs per game between the best and worst order (about 21 a season)
TRIES = 3
DEALS = 300             # deals tried per draw (cheap); the most realistic, most varied one is scored
ROUND = 5               # decimals kept for the rates (the page and the build use the same numbers)
POS_ORDER = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
TARGET = ["star", "eye", "slugger", "slugger", "contact", "singles", "weak", "weak", "any"]
# The nine's average OBP and SLG: the 10th-90th percentile of real team-seasons since 1955
# (players.team_seasons: OBP .305-.343, median .324; SLG .355-.439, median .395).
REALISTIC = {"obp": (0.305, 0.343), "slg": (0.355, 0.439)}
MEDIAN_TEAM = {"obp": 0.324, "slg": 0.395}
KIND_LABEL = {"star": "Star", "eye": "Walk machine", "slugger": "Slugger", "contact": "Contact hitter",
              "singles": "Singles hitter", "weak": "Light hitter"}


def kinds(s: dict) -> list[str]:
    """The hitter types a season fits (rates per plate appearance)."""
    k, bb, b1, b2, b3, hr, _ = s["rates"]
    iso = s["slg"] - s["avg"]
    out = []
    if s["obp"] >= 0.390 and s["slg"] >= 0.520:
        out.append("star")
    if bb >= 0.13 and iso <= 0.170:
        out.append("eye")
    if hr >= 0.05 and k >= 0.20:
        out.append("slugger")
    if k <= 0.08 and s["avg"] >= 0.290 and bb <= 0.08:
        out.append("contact")
    if b1 / max(b1 + b2 + b3 + hr, 1e-9) >= 0.78 and iso <= 0.100:
        out.append("singles")
    if s["obp"] <= 0.300:
        out.append("weak")
    return out


def rounded_rates(rates: list[float]) -> list[float]:
    r = [round(x, ROUND) for x in rates[:-1]]
    return r + [round(1 - sum(r), ROUND)]


def deal(rng: random.Random, pool: dict[tuple[str, str], list[dict]], by_pos: dict[str, list[dict]],
         banned: set[str]) -> list[dict] | None:
    """Nine seasons, one per position, covering as many of TARGET's types as the pool allows."""
    targets = TARGET[:]
    rng.shuffle(targets)
    positions = POS_ORDER[:]
    rng.shuffle(positions)
    chosen: dict[str, dict] = {}
    today: set[str] = set()
    used = set(banned)
    for pos in positions:
        options = [t for t in dict.fromkeys(targets)
                   if t == "any" or any(s["id"] not in used for s in pool.get((t, pos), []))]
        kind = options[0] if options else "any"
        if kind in targets:
            targets.remove(kind)
        cands = [s for s in (by_pos[pos] if kind == "any" else pool[(kind, pos)]) if s["id"] not in used]
        if not cands:   # everyone here was used recently: allow a repeat, but not one already in today's nine
            cands = [s for s in by_pos[pos] if s["id"] not in today]
        if not cands:
            return None
        s = rng.choices(cands, weights=[c["fame"] ** 0.5 for c in cands])[0]   # sqrt: regulars too, not only stars
        chosen[pos] = {**s, "kind": kind, "slot": pos}
        used.add(s["id"])
        today.add(s["id"])
    return [chosen[p] for p in POS_ORDER]


def off_realistic(nine: list[dict]) -> float:
    """How far the nine's average OBP and SLG fall outside REALISTIC (0 = a real team's range)."""
    out = 0.0
    for k, (lo, hi) in REALISTIC.items():
        m = sum(s[k] for s in nine) / len(nine)
        out += max(lo - m, 0.0, m - hi)
    return out


def off_median(nine: list[dict]) -> float:
    return sum(abs(sum(s[k] for s in nine) / len(nine) - m) for k, m in MEDIAN_TEAM.items())


def card(s: dict) -> dict:
    kind = s["kind"] if s["kind"] != "any" else next(iter(kinds(s)), "")   # label what the season is
    plays = s["pos"] if s["slot"] == "DH" and s["pos"] != "DH" else ""     # a fielder batting DH
    return {"id": s["id"], "name": s["name"], "year": s["year"], "team": s["team"], "pos": s["slot"], "plays": plays,
            "type": KIND_LABEL.get(kind, ""), "pa": s["pa"],
            "avg": round(s["avg"], 3), "obp": round(s["obp"], 3), "slg": round(s["slg"], 3),
            "hr": s["hr"], "bb": s["bb"], "so": s["so"], "rates": rounded_rates(s["rates"])}


def score(cards: list[dict], rules: dict) -> dict:
    orders, runs = chain.all_orders([c["rates"] for c in cards], rules)
    best, worst = int(runs.argmax()), int(runs.argmin())
    return {"best": {"order": [int(i) for i in orders[best]], "runs": round(float(runs[best]), 6)},
            "worst": {"order": [int(i) for i in orders[worst]], "runs": round(float(runs[worst]), 6)},
            "percentiles": [round(float(x), 6) for x in np.percentile(runs, range(101))],
            "orders": len(runs)}


def generate(seasons: list[dict], fame: dict[str, float], start: dt.date, end: dt.date,
             rules: dict | None = None, log=print) -> list[dict]:
    rules = rules or chain.load_rules()
    pool: dict[tuple[str, str], list[dict]] = {}
    by_pos: dict[str, list[dict]] = {p: [] for p in POS_ORDER}
    for s in seasons:
        f = fame.get(s["id"], 0.0)
        if f < FAME_FLOOR:
            continue
        s = {**s, "fame": f}
        for slot in {s["pos"], "DH"}:          # anyone can bat DH
            by_pos[slot].append(s)
            for k in kinds(s):
                pool.setdefault((k, slot), []).append(s)
    out, recent = [], []          # recent: (date, player ids)
    day, number = start, 1
    while day <= end:
        rng = random.Random(f"lineup-{day.isoformat()}")
        banned = {pid for d, ids in recent if (day - d).days <= REPEAT_DAYS for pid in ids}
        best = None
        for _ in range(TRIES):
            deals = [d for d in (deal(rng, pool, by_pos, banned) for _ in range(DEALS)) if d]
            if not deals:
                continue
            nine = min(deals, key=lambda d: (off_realistic(d), -sum(1 for s in d if kinds(s)), off_median(d)))
            cards = [card(s) for s in nine]
            sc = score(cards, rules)
            gap = sc["best"]["runs"] - sc["worst"]["runs"]
            if best is None or gap > best[0]:
                best = (gap, cards, sc)
            if gap >= MIN_GAP:
                break
        if best is None:
            raise RuntimeError(f"no lineup puzzle for {day}")
        _, cards, sc = best
        out.append({"date": day.isoformat(), "number": number, "players": cards, **sc,
                    "rules": {"advance": rules["advance"], "game": rules["game"]}})
        recent.append((day, {c["id"] for c in cards}))
        day += dt.timedelta(days=1)
        number += 1
    log(f"generated {len(out)} lineup puzzles {start} .. {end}")
    return out
