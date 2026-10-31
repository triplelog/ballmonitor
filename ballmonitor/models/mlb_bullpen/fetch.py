"""Download MLB box scores + play-by-play and build the mlb_bullpen datasets.

    ballmonitor fetch mlb_bullpen            # download missing games (cached) and rebuild
    ballmonitor fetch mlb_bullpen --offline  # rebuild from data/raw/ only

Writes:
    data/raw/schedule_<season>.json        regular-season schedule (MLB Stats API)
    data/raw/<season>/box_<pk>.json.gz     box score (field-filtered), one per game
    data/raw/<season>/pbp_<pk>.json.gz     play-by-play (field-filtered), one per game
    data/raw/people_<n>.json.gz            throwing / batting hands
    data/raw/rosters/<season>/r_<team>_<date>.json.gz   active roster on a date (game day
                                           and the day before)
    data/raw/transactions/tx_<season>_<team>.json.gz    transactions (injured-list diagnostic)
    data/games.csv.gz     one row per team-game (both seasons): PRE-GAME inputs + outcome
    data/decisions.csv.gz one row per bullpen call: game state at the call + who came in
    data/pitcher_lines.csv.gz  one row per pitcher appearance (both seasons, from opening day):
                          outs (box score), batters faced and runs scored while on the mound
                          (play-by-play); used by research_runs.py
    data/backtest.csv     every BACKTEST_EVERY-th 2026 team-game (test season) for
                          `ballmonitor backtest mlb_bullpen`

Leakage rules (every input column is known before first pitch):
  * workloads (`pitches_days`) come from earlier games only (doubleheader game 2 sees game 1,
    folded into the "yesterday" slot);
  * usage history (apps, saves, holds, ...) is the pitcher's last WINDOW roster-games before
    this game, with any team, across seasons;
  * `starter_stamina` is the mean pitch count of the starter's last STARTS_KEPT earlier starts;
  * the bullpen pool is the game-day active roster's pitchers minus today's starter and
    rotation arms (last outing a start of ROTATION_MIN_PITCHES+ within ROTATION_DAYS days);
  * lineup handedness is the opponent's posted batting order;
  * `off_day_tomorrow` comes from the published schedule;
  * the pool comes from the box-score roster = the active roster at game time, so arms on the
    IL / optioned / DFA'd before the game are already excluded. Per reliever `new_arrival` = 1
    when he was not on the previous day's active roster (MLB Stats API roster endpoint):
    joined today (recalled, activated, acquired) -- announced before first pitch. The API
    roster *for the game date* is an end-of-day state (it drops arms optioned or put on the
    IL after pitching that day), so it is NOT used as an input; `off_roster_eod` records the
    pool arms missing from it, as a diagnostic;
  * run prevention (v0.6.0): per reliever `ra_outs` / `ra_runs` = outs recorded and runs
    scored while he was on the mound over ALL his earlier relief outings in the data (any
    team, both seasons); `team_bp_outs` / `team_bp_runs` = the team's relievers over its
    earlier games this season; `starter_prior_outs` / `starter_prior_runs` = today's starter
    over his earlier starts this season. "Runs on the mound" = runs that scored during plate
    appearances he pitched (play-by-play score changes), so inherited runners who score count
    against the pitcher on the mound, not the one who put them on (no earned/unearned split:
    the cached box scores carry no per-pitcher R/ER/H/BB/K);
  * team tendency: `team_recent_relievers` = pool relievers used per game over the team's
    last TEAM_WINDOW_GAMES games on EARLIER dates (`team_recent_games` = how many),
    `league_recent_relievers` = league mean over the previous LEAGUE_WINDOW_DAYS days.
Outcome columns (`actual_relievers_used`, `first_reliever`, `starter_pitches`, `pool_used`,
`later_il`, `off_roster_eod`, `starter_runs`, `bullpen_outs`, `bullpen_runs`, ...) are only used for scoring and diagnostics; `roster_departed`
(pitchers on yesterday's active roster who are not on today's game roster) is pre-game but
only used as a diagnostic. `later_il` (pool relievers placed on
the injured list 1-3 days after the game) is post-game information: never an input.

Source: MLB Stats API (statsapi.mlb.com), free, no key. Stdlib only.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import time
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0 (ballmonitor mlb_bullpen fetch)"}
SCHEDULE_URL = (
    API + "/schedule?sportId=1&season={season}&gameType=R&fields=dates,date,games,gamePk,"
    "gameType,gameNumber,status,abstractGameState,detailedState,teams,home,away,team,id"
)
BOX_URL = (
    API + "/game/{pk}/boxscore?fields=teams,home,away,team,id,abbreviation,players,person,"
    "fullName,position,code,stats,pitching,numberOfPitches,gamesStarted,saves,holds,"
    "gamesFinished,outs,pitchers,battingOrder"
)
PBP_URL = (
    API + "/game/{pk}/playByPlay?fields=allPlays,about,inning,isTopInning,result,awayScore,"
    "homeScore,count,outs,matchup,pitcher,id,batter,postOnFirst,postOnSecond,postOnThird,"
    "batSide,code"
)
PEOPLE_URL = API + "/people?personIds={ids}&fields=people,id,pitchHand,batSide,code"
ROSTER_URL = API + "/teams/{team}/roster?rosterType=active&date={date}&fields=roster,person,id"
TRANSACTIONS_URL = (
    API + "/transactions?teamId={team}&startDate={start}&endDate={end}&fields=transactions,"
    "person,id,date,effectiveDate,typeCode,description"
)

SEASONS = (2025, 2026)
CASES_FROM = "2025-04-15"  # the first ~3 weeks of 2025 only build usage history
TEST_FROM = "2026-01-01"  # 2026 = held-out test season (research.py fits on 2025)
WINDOW = 30  # roster-games of usage history kept per pitcher
STARTS_KEPT = 5  # starts averaged for starter_stamina
ROTATION_DAYS = 10
ROTATION_MIN_PITCHES = 50
MIN_POOL = 5
TEAM_WINDOW_GAMES = 80  # team tendency window (research.py grid on 2025)
LEAGUE_WINDOW_DAYS = 30
IL_LOOKAHEAD_DAYS = 3  # later_il diagnostic only
BACKTEST_EVERY = 8  # backtest.csv keeps every 8th 2026 team-game (~600 rows)
WORKERS = 4  # polite parallelism
FINAL_STATES = ("Final", "Game Over", "Completed Early")

GAME_FIELDS = [
    "game_pk", "game_date", "season", "team", "opponent", "is_home", "off_day_tomorrow",
    "starter_name", "starter_hand", "starter_stamina", "lineup", "relievers_json",
    "team_recent_games", "team_recent_relievers", "league_recent_relievers",
    "actual_relievers_used", "first_reliever", "n_relievers", "starter_pitches",
    "starter_outs", "runs_for", "runs_against", "pool_used", "later_il",
    "off_roster_eod", "roster_departed",
    # run prevention (v0.6.0): pre-game season-to-date team bullpen / starter lines, and the
    # game's actual runs scored while the starter / the bullpen was on the mound (outcomes)
    "team_bp_outs", "team_bp_runs", "starter_prior_outs", "starter_prior_runs",
    "starter_runs", "bullpen_outs", "bullpen_runs",
]
LINE_FIELDS = ["seq", "game_pk", "game_date", "season", "team", "pitcher_id", "name", "started", "outs", "bf", "runs"]
DECISION_FIELDS = [
    "game_pk", "team", "call", "inning", "outs", "on_1b", "on_2b", "on_3b", "lead",
    "next_hands", "chosen",
]


def _get(url: str, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def _cached(url: str, path: Path, offline: bool) -> dict | None:
    """GET url (JSON), caching the response gzipped under data/raw/ (gitignored)."""
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    if offline:
        return None
    data = json.loads(_get(url))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)
    tmp.replace(path)  # atomic: a half-written file is never read as a cache hit
    return data


def _schedule(raw: Path, season: int, offline: bool) -> list[dict]:
    path = raw / f"schedule_{season}.json"
    if not offline and (not path.exists() or season == max(SEASONS)):
        path.write_bytes(_get(SCHEDULE_URL.format(season=season)))
    if not path.exists():
        return []
    games: dict[int, dict] = {}
    for d in json.loads(path.read_text()).get("dates", []):
        for g in d.get("games", []):
            if g.get("gameType") != "R":
                continue
            final = g.get("status", {}).get("detailedState") in FINAL_STATES
            g = dict(g, date=d["date"], season=season, final=final)
            if final:
                games[g["gamePk"]] = g  # postponed copies are not Final; last Final wins
            else:
                games[-g["gamePk"]] = g  # not played on this date: only used for off days
    return list(games.values())


def _hands(ids: set[int], raw: Path, offline: bool) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    todo = sorted(ids)
    for i in range(0, len(todo), 100):
        chunk = todo[i : i + 100]
        key = f"{chunk[0]}_{chunk[-1]}_{len(chunk)}"
        data = _cached(PEOPLE_URL.format(ids=",".join(map(str, chunk))),
                       raw / f"people_{key}.json.gz", offline)
        for person in (data or {}).get("people", []):
            pitch = person.get("pitchHand", {}).get("code", "R")
            out[person["id"]] = {
                "pitch": pitch if pitch in ("R", "L") else "R",  # ambidextrous ("S") -> R
                "bat": person.get("batSide", {}).get("code", "R"),
            }
    return out


def _rosters(raw: Path, team_dates: set[tuple[int, str]], offline: bool) -> dict[tuple[int, str], set[int]]:
    """Active-roster person ids per (team id, date) from the MLB Stats API roster endpoint
    (cached gzipped in data/raw/rosters/). Missing / failed requests are simply absent."""

    def one(key: tuple[int, str]):
        team, d = key
        path = raw / "rosters" / d[:4] / f"r_{team}_{d}.json.gz"
        try:
            data = _cached(ROSTER_URL.format(team=team, date=d), path, offline)
        except Exception:
            return key, None
        if data is None:
            return key, None
        return key, {int(x["person"]["id"]) for x in data.get("roster", [])}

    with ThreadPoolExecutor(WORKERS) as pool:
        res = list(pool.map(one, sorted(team_dates)))
    return {k: v for k, v in res if v is not None}


def _injured_list_dates(raw: Path, teams: set[int], offline: bool) -> dict[int, list[tuple[str, str]]]:
    """person id -> [(transaction date, retroactive-to date)] for injured-list placements
    (MLB Stats API transactions, cached). DIAGNOSTIC ONLY: placements are announced after
    the fact (often retroactive), so they are never a pre-game input."""
    import re

    out: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for season in SEASONS:
        for team in sorted(teams):
            path = raw / "transactions" / f"tx_{season}_{team}.json.gz"
            try:
                data = _cached(TRANSACTIONS_URL.format(team=team, start=f"{season}-02-01",
                                                       end=f"{season}-11-30"), path, offline)
            except Exception:
                continue
            for t in (data or {}).get("transactions", []):
                desc = t.get("description", "")
                if "placed" not in desc or "injured list" not in desc:
                    continue
                m = re.search(r"retroactive to (\w+ \d+, \d{4})", desc)
                retro = t.get("date", "")[:10]
                if m:
                    try:
                        from datetime import datetime
                        retro = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
                    except ValueError:
                        pass
                pid = t.get("person", {}).get("id")
                if pid:
                    out[int(pid)].append((t.get("date", "")[:10], retro))
    return out


def _decisions(pbp: dict, side: str, names: dict[int, str], bats: dict[int, str]) -> list[dict]:
    """Every pitching change by `side` ('home'/'away'): game state just before it.
    `next_hands` = listed batting side (L/R/S, from the people endpoint) of the next 3
    batters, so a switch hitter is "S" whoever pitches."""
    defend_top = side == "home"
    plays = [p for p in pbp.get("allPlays", []) if p.get("about", {}).get("isTopInning") == defend_top]
    all_plays = pbp.get("allPlays", [])
    out = []
    current = None
    prev_by_half: dict[int, dict] = {}
    last_score = {"awayScore": 0, "homeScore": 0}
    score_before: dict[int, dict] = {}
    for p in all_plays:  # score before each play
        score_before[id(p)] = dict(last_score)
        res = p.get("result", {})
        if "awayScore" in res:
            last_score = {"awayScore": res["awayScore"], "homeScore": res.get("homeScore", 0)}
    for idx, p in enumerate(plays):
        m = p.get("matchup", {})
        pid = m.get("pitcher", {}).get("id")
        inning = p["about"]["inning"]
        prev = prev_by_half.get(inning)
        if current is not None and pid != current:
            if prev is None:  # change between innings
                outs, on1, on2, on3 = 0, 0, int(inning >= 10), 0
            else:
                pm = prev.get("matchup", {})
                outs = prev.get("count", {}).get("outs", 0)
                on1, on2, on3 = (int(bool(pm.get(k))) for k in ("postOnFirst", "postOnSecond", "postOnThird"))
                if outs >= 3:
                    outs, on1, on2, on3 = 0, 0, 0, 0
            sb = score_before[id(p)]
            ours, theirs = (sb["homeScore"], sb["awayScore"]) if side == "home" else (sb["awayScore"], sb["homeScore"])
            nxt = [bats.get(q.get("matchup", {}).get("batter", {}).get("id"), "R") for q in plays[idx : idx + 3]]
            out.append({
                "inning": inning, "outs": outs, "on_1b": on1, "on_2b": on2, "on_3b": on3,
                "lead": ours - theirs, "next_hands": ",".join(nxt), "chosen": names.get(pid, str(pid)),
            })
        current = pid
        prev_by_half[inning] = p
    return out


def _runs_on_mound(pbp: dict, side: str) -> dict[int, list[int]]:
    """pitcher id -> [batters faced, runs scored while he pitched] for the defending `side`
    ('home' defends the top halves). A run belongs to the pitcher of the plate appearance in
    which it scored (score change from the previous play)."""
    defend_top = side == "home"
    out: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    prev = 0
    key = "awayScore" if defend_top else "homeScore"  # runs scored against `side`
    for p in pbp.get("allPlays", []):
        res = p.get("result", {})
        score = res.get(key, prev) if key in res else prev
        if p.get("about", {}).get("isTopInning") == defend_top:
            pid = p.get("matchup", {}).get("pitcher", {}).get("id")
            if pid is not None:
                out[int(pid)][0] += 1
                out[int(pid)][1] += max(0, score - prev)
        prev = score
    return out


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    data_dir = model_dir / "data"
    raw = data_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    log: list[str] = []

    sched = [g for s in SEASONS for g in _schedule(raw, s, offline)]
    final = sorted((g for g in sched if g["final"]), key=lambda g: (g["date"], g.get("gameNumber", 1), g["gamePk"]))
    play_days: dict[int, set[str]] = defaultdict(set)  # team id -> scheduled dates
    for g in sched:
        for side in ("home", "away"):
            play_days[g["teams"][side]["team"]["id"]].add(g["date"])
    log.append(f"Schedule: {len(final)} final regular-season games in {', '.join(map(str, SEASONS))}.")

    def load(g: dict) -> tuple[dict, dict | None, dict | None]:
        pk, folder = g["gamePk"], raw / str(g["season"])
        try:
            box = _cached(BOX_URL.format(pk=pk), folder / f"box_{pk}.json.gz", offline)
            pbp = _cached(PBP_URL.format(pk=pk), folder / f"pbp_{pk}.json.gz", offline)
        except Exception:
            return g, None, None
        return g, box, pbp

    with ThreadPoolExecutor(WORKERS) as pool:
        loaded = list(pool.map(load, final))
    loaded = [x for x in loaded if x[1] is not None and x[2] is not None]
    log.append(f"Box scores + play-by-play available for {len(loaded)} games (cached in data/raw/).")

    ids: set[int] = set()
    for _, box, _ in loaded:
        for side in ("home", "away"):
            t = box["teams"][side]
            ids.update(int(p["person"]["id"]) for p in t["players"].values() if p.get("position", {}).get("code") in ("1", "Y"))
            ids.update(int(b) for b in t.get("battingOrder", []))
            ids.update(int(p["person"]["id"]) for p in t["players"].values())
    hands = _hands(ids, raw, offline)
    bats = {pid: h["bat"] for pid, h in hands.items()}

    team_dates: set[tuple[int, str]] = set()
    for g, box, _ in loaded:
        for side in ("home", "away"):
            tid = box["teams"][side]["team"]["id"]
            team_dates.add((tid, g["date"]))
            team_dates.add((tid, (date.fromisoformat(g["date"]) - timedelta(days=1)).isoformat()))
    rosters = _rosters(raw, team_dates, offline)
    known_pitchers = {int(p["person"]["id"]) for _, box, _ in loaded for side in ("home", "away")
                      for p in box["teams"][side]["players"].values() if p.get("position", {}).get("code") == "1"}
    il_dates = _injured_list_dates(raw, {t for t, _ in team_dates}, offline)
    log.append(f"Active rosters available for {len(rosters)} of {len(team_dates)} team-dates (cached).")

    # Per-pitcher state, updated after each game (so rows only see earlier games).
    pitches_on: dict[int, dict[str, int]] = defaultdict(dict)  # pid -> date -> pitches
    usage: dict[int, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
    starts: dict[int, deque] = defaultdict(lambda: deque(maxlen=STARTS_KEPT))
    last_out: dict[int, tuple[str, bool, int]] = {}  # pid -> (date, started, pitches)
    relief_ra: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # pid -> [outs, runs], all relief
    start_ra: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])  # (season, pid), starts
    team_bp: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])  # (season, team id)

    games_rows: list[dict] = []
    line_rows: list[dict] = []
    dec_rows: list[dict] = []
    for g, box, pbp in loaded:
        d_str = g["date"]
        day = date.fromisoformat(d_str)
        prior_days = [(day - timedelta(days=k)).isoformat() for k in range(1, 6)]
        sides = {}
        for side, other in (("home", "away"), ("away", "home")):
            t, o = box["teams"][side], box["teams"][other]
            pitchers = [int(x) for x in t.get("pitchers", [])]
            if not pitchers:
                continue
            players = {int(p["person"]["id"]): p for p in t["players"].values()}
            names = {pid: p["person"]["fullName"] for pid, p in players.items()}
            sides[side] = (t, o, pitchers, players, names)
        mound = {side: _runs_on_mound(pbp, side) for side in sides}
        outs_of = {side: {pid: int(v[3].get(pid, {}).get("stats", {}).get("pitching", {}).get("outs", 0) or 0)
                          for pid in v[2]} for side, v in sides.items()}

        for side, (t, o, pitchers, players, names) in sides.items():
            team_id = t["team"]["id"]
            starter = pitchers[0]
            roster_p = [pid for pid, p in players.items() if p.get("position", {}).get("code") == "1"]
            on_today = rosters.get((team_id, d_str))
            on_before = rosters.get((team_id, prior_days[0]))
            if on_before is not None and len(on_before) < 20:  # pre-season / missing roster
                on_before = None
            later_il, off_eod = [], []
            pool = []
            for pid in roster_p:
                if pid == starter:
                    continue
                lo = last_out.get(pid)
                if lo and lo[1] and lo[2] >= ROTATION_MIN_PITCHES and (day - date.fromisoformat(lo[0])).days <= ROTATION_DAYS:
                    continue  # rotation arm between starts
                hist = pitches_on[pid]
                pdays = [hist.get(x, 0) for x in prior_days]
                pdays[0] += hist.get(d_str, 0)  # doubleheader game 2: game 1 counts as most recent
                u = usage[pid]
                pool.append({
                    "name": names[pid],
                    "hand": hands.get(pid, {}).get("pitch", "R"),
                    "pitches_days": pdays,
                    "games": len(u),
                    "apps": sum(r[0] for r in u),
                    "firsts": sum(r[1] for r in u),
                    "saves": sum(r[2] for r in u),
                    "holds": sum(r[3] for r in u),
                    "finishes": sum(r[4] for r in u),
                    "outs": sum(r[5] for r in u),
                    "ra_outs": relief_ra[pid][0] if pid in relief_ra else 0,
                    "ra_runs": relief_ra[pid][1] if pid in relief_ra else 0,
                })
                if on_today is not None and pid not in on_today:
                    off_eod.append(len(pool) - 1)  # diagnostic only (end-of-day roster)
                if on_before is not None and pid not in on_before:
                    pool[-1]["new_arrival"] = 1
                if any(d_str < tx <= (day + timedelta(days=IL_LOOKAHEAD_DAYS)).isoformat()
                       for tx, _ in il_dates.get(pid, [])):
                    later_il.append(len(pool) - 1)
            seen: set[str] = set()
            for r in pool:  # duplicate full names on one roster: disambiguate
                if r["name"] in seen:
                    r["name"] += " (2)"
                seen.add(r["name"])
            used = [names.get(pid, str(pid)) for pid in pitchers[1:]]
            pool_names = {r["name"] for r in pool}
            later_il = [pool[i]["name"] for i in later_il]
            off_eod = [pool[i]["name"] for i in off_eod]
            # pitchers on yesterday's active roster who are not on today's game roster
            departed = len((on_before & known_pitchers) - set(players)) if on_before is not None else ""
            st = players[starter].get("stats", {}).get("pitching", {})
            prior_starts = starts[starter]
            opp_bo = [int(b) for b in o.get("battingOrder", [])][:9]
            plays = pbp.get("allPlays", [])
            last = plays[-1].get("result", {}) if plays else {}
            rf, ra = (last.get("homeScore", 0), last.get("awayScore", 0)) if side == "home" else (last.get("awayScore", 0), last.get("homeScore", 0))
            row = {
                "game_pk": g["gamePk"], "game_date": d_str, "season": g["season"],
                "team": t["team"].get("abbreviation", str(team_id)),
                "opponent": o["team"].get("abbreviation", ""),
                "is_home": int(side == "home"),
                "off_day_tomorrow": int((day + timedelta(days=1)).isoformat() not in play_days[team_id]),
                "starter_name": names[starter],
                "starter_hand": hands.get(starter, {}).get("pitch", "R"),
                "starter_stamina": round(sum(prior_starts) / len(prior_starts)) if prior_starts else "",
                "lineup": ",".join(hands.get(b, {}).get("bat", "R") for b in opp_bo) or ",".join(["R"] * 9),
                "relievers_json": json.dumps(pool, separators=(",", ":")),
                "actual_relievers_used": ";".join(used),
                "first_reliever": used[0] if used else "None",
                "n_relievers": len(used),
                "starter_pitches": st.get("numberOfPitches", 0),
                "starter_outs": st.get("outs", 0),
                "runs_for": rf, "runs_against": ra,
                "pool_used": len(set(used) & pool_names),
                "later_il": ";".join(later_il),
                "off_roster_eod": ";".join(off_eod),
                "roster_departed": departed,
                "team_bp_outs": team_bp[(g["season"], team_id)][0] if (g["season"], team_id) in team_bp else 0,
                "team_bp_runs": team_bp[(g["season"], team_id)][1] if (g["season"], team_id) in team_bp else 0,
                "starter_prior_outs": start_ra[(g["season"], starter)][0] if (g["season"], starter) in start_ra else 0,
                "starter_prior_runs": start_ra[(g["season"], starter)][1] if (g["season"], starter) in start_ra else 0,
                "starter_runs": mound[side].get(starter, [0, 0])[1],
                "bullpen_outs": sum(outs_of[side][pid] for pid in pitchers[1:]),
                "bullpen_runs": sum(mound[side].get(pid, [0, 0])[1] for pid in pitchers[1:]),
            }
            if d_str >= CASES_FROM and len(pool) >= MIN_POOL:
                games_rows.append(row)
                for i, dec in enumerate(_decisions(pbp, side, names, bats), 1):
                    dec_rows.append({"game_pk": g["gamePk"], "team": row["team"], "call": i, **dec})

        # Update state with this game's results.
        for side, (t, o, pitchers, players, names) in sides.items():
            tkey = (g["season"], t["team"]["id"])
            for k, pid in enumerate(pitchers):
                outs_runs = (outs_of[side][pid], mound[side].get(pid, [0, 0])[1])
                line_rows.append({
                    "seq": len(line_rows), "game_pk": g["gamePk"], "game_date": d_str, "season": g["season"],
                    "team": t["team"].get("abbreviation", ""), "pitcher_id": pid, "name": names.get(pid, str(pid)),
                    "started": int(k == 0), "outs": outs_runs[0], "bf": mound[side].get(pid, [0, 0])[0],
                    "runs": outs_runs[1],
                })
                acc = start_ra[(g["season"], pid)] if k == 0 else relief_ra[pid]
                acc[0] += outs_runs[0]; acc[1] += outs_runs[1]
                if k:
                    team_bp[tkey][0] += outs_runs[0]; team_bp[tkey][1] += outs_runs[1]
            first_rel = pitchers[1] if len(pitchers) > 1 else None
            for pid, p in players.items():
                if p.get("position", {}).get("code") not in ("1", "Y"):
                    continue
                s = p.get("stats", {}).get("pitching", {})
                n = int(s.get("numberOfPitches", 0) or 0)
                appeared = pid in pitchers
                started = appeared and pid == pitchers[0]
                if appeared:
                    pitches_on[pid][d_str] = pitches_on[pid].get(d_str, 0) + n
                    last_out[pid] = (d_str, started, n)
                if started:
                    starts[pid].append(n)
                elif p.get("position", {}).get("code") == "1":
                    usage[pid].append((
                        int(appeared), int(pid == first_rel), int(s.get("saves", 0) or 0),
                        int(s.get("holds", 0) or 0), int(s.get("gamesFinished", 0) or 0),
                        int(s.get("outs", 0) or 0) if appeared else 0,
                    ))

    # Team / league bullpen-usage tendency from earlier dates only (tendency.py).
    from ballmonitor.models.mlb_bullpen.tendency import rolling_usage

    roll = rolling_usage(games_rows, TEAM_WINDOW_GAMES, LEAGUE_WINDOW_DAYS)
    for row in games_rows:
        v = roll[(str(row["game_pk"]), row["team"])]
        row["team_recent_games"] = v["team_recent_games"]
        row["team_recent_relievers"] = "" if v["team_recent_relievers"] is None else v["team_recent_relievers"]
        row["league_recent_relievers"] = "" if v["league_recent_relievers"] is None else v["league_recent_relievers"]

    with gzip.open(data_dir / "games.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GAME_FIELDS)
        w.writeheader()
        w.writerows(games_rows)
    with gzip.open(data_dir / "decisions.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=DECISION_FIELDS)
        w.writeheader()
        w.writerows(dec_rows)
    with gzip.open(data_dir / "pitcher_lines.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LINE_FIELDS)
        w.writeheader()
        w.writerows(line_rows)
    test = [r for r in games_rows if r["game_date"] >= TEST_FROM]
    sample = test[::BACKTEST_EVERY]
    with open(data_dir / "backtest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=GAME_FIELDS)
        w.writeheader()
        w.writerows(sample)
    log.append(
        f"Wrote {len(games_rows)} team-games -> games.csv.gz, {len(dec_rows)} bullpen calls -> "
        f"decisions.csv.gz, {len(line_rows)} pitcher lines -> pitcher_lines.csv.gz, {len(sample)} sampled 2026 team-games -> backtest.csv."
    )
    return log


def read_csv_gz(path: Path) -> list[dict[str, str]]:
    """Helper for research.py: read a gzipped CSV written by fetch()."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(io.StringIO(fh.read())))
