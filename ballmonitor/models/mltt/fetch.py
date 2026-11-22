"""Build the MLTT data from the league's own results API (web.mltt.com, the site behind
mltt.com/results).

    ballmonitor fetch mltt [--offline] [--scheduled]

Endpoints (public, JSON, no key):
  /api/seasons                                  season ids (Season 1 has no events)
  /api/schedules?seasonId=<id>&limit=100        the season's weekends ("events")
  /api/schedules/<event id>/matches             the weekend's matches (team points once played)
  /api/results?matchId=<uuid>&team1Id=&team2Id= box score: per matchup the player(s) and the
                                                three game scores; Golden Game score and rallies
                                                won by each player
  /api/standings                                the current season's standings (a check)

Writes (data/):
  matches.csv   one row per match (played or scheduled)
  games.csv     one row per Stage One game (5 matchups x 3 games per match)
  golden.csv    one row per player per Golden Game (rallies won during their turns)
  players.csv   every player seen: name, gender, MLTT rating as of the fetch, last team
  teams.csv     team, division, colour
  ratings_history.csv  every player's SPINDEX rating changes, dated (spindex.mltt.com
                /api/public/players/<id>/rating-history): the rating as of any day
  meta.json     fetch time, counts, standings check

Raw responses are cached in data/raw/mltt/ (gitignored); --offline rebuilds from it. With
scheduled=True (the daily CI build) only the current season is downloaded again; earlier
seasons' rows are kept from the committed CSVs. Uses only the standard library.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://web.mltt.com/api"
# SPINDEX, MLTT's player rating (spindex.mltt.com): each player's dated rating history, public JSON
SPINDEX = "https://spindex.mltt.com/api/public/players/{id}/rating-history"
UA = "Mozilla/5.0 (compatible; ballmonitor data fetch)"
# Order the matchups are played in (mltt.com/format): men's singles, women's singles,
# open-serve doubles, singles 3, singles 4. The API's keys in that order.
MATCHUPS = ("singles_1", "singles_2", "doubles_1", "singles_3", "singles_4")
MATCH_COLS = ["season", "match_id", "date", "start", "event", "city", "venue", "team_a", "team_b",
              "points_a", "points_b", "stage_one_a", "stage_one_b", "golden_a", "golden_b", "status", "stage"]
GAME_COLS = ["season", "match_id", "date", "order", "matchup", "game", "team_a", "team_b",
             "a1", "a2", "b1", "b2", "points_a", "points_b"]
GOLDEN_COLS = ["season", "match_id", "date", "team", "opponent", "head_start", "score", "opp_score",
               "player", "rallies_won"]
HISTORY_COLS = ["spindex_id", "date", "old_rating", "new_rating", "event", "created"]
PLAYER_COLS = ["player_id", "name", "gender", "mltt_rating", "spindex_id", "hand", "citizenship", "team", "last_season"]


class Fetcher:
    def __init__(self, raw_dir: Path, offline: bool, delay: float = 0.2):
        self.raw_dir, self.offline, self.delay = raw_dir, offline, delay
        self.requests = 0
        raw_dir.mkdir(parents=True, exist_ok=True)

    def get(self, path: str, refresh: bool = True) -> Any:
        """GET API+path (or a full URL). `refresh=False`: use the cached copy when there is one."""
        key = hashlib.sha1(path.encode()).hexdigest()[:16]
        cache = self.raw_dir / f"{key}.json"
        if cache.exists() and (self.offline or not refresh):
            return json.loads(cache.read_text())
        if self.offline:
            raise FileNotFoundError(f"--offline but {path} is not cached ({cache})")
        last: Exception | None = None
        for attempt in range(4):
            try:
                time.sleep(self.delay * (2 ** attempt))
                url = path if path.startswith("https://") else API + path
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                self.requests += 1
                cache.write_text(json.dumps(data))
                return data
            except Exception as exc:  # network hiccup: retry with backoff
                last = exc
        raise RuntimeError(f"failed to fetch {path}: {last}")


def _season_no(name: str) -> int:
    return int(name.split()[-1])


def _pid(p: dict | None) -> str:
    return (p or {}).get("id") or ""


def _played(m: dict, res: dict | None) -> bool:
    if not res:
        return False
    a, b = res["teamA"], res["teamB"]
    return (a["team_score"] + b["team_score"]) > 0 and a["singles_1"].get("player") is not None


def season_rows(f: Fetcher, season: dict, players: dict, teams: dict, today: dt.date) -> tuple[list, list, list]:
    sno = _season_no(season["seasonName"])
    events = f.get(f"/schedules?seasonId={season['id']}&limit=100")["data"]
    events = sorted(events, key=lambda e: e["startDate"])
    last_event = events[-1]["id"] if events else None
    matches, games, golden = [], [], []
    for ev in events:
        ev_ms = f.get(f"/schedules/{ev['id']}/matches")
        for m in sorted(ev_ms, key=lambda m: m["startDateTime"]):
            date = dt.date.fromisoformat(m["date"])
            # finished matches never change: reuse the cache; refresh the recent and the future
            q = urllib.parse.urlencode({"matchId": m["id"], "team1Id": m["team1Id"], "team2Id": m["team2Id"]})
            res = f.get(f"/results?{q}", refresh=date >= today - dt.timedelta(days=10))
            played = _played(m, res)
            ta, tb = m["team1"]["name"], m["team2"]["name"]
            # The season's last weekend is the Final Four (semifinals + final) once the season has one
            stage = "playoff" if (ev["id"] == last_event and "hampionship" in (ev.get("venue") or "")) else "regular"
            row = {"season": sno, "match_id": m["id"], "date": m["date"], "start": m["startDateTime"],
                   "event": ev["id"], "city": ev.get("city") or "", "venue": ev.get("venue") or "",
                   "team_a": ta, "team_b": tb, "points_a": "", "points_b": "", "stage_one_a": "", "stage_one_b": "",
                   "golden_a": "", "golden_b": "", "status": "final" if played else "scheduled", "stage": stage}
            if played:
                A, B = res["teamA"], res["teamB"]
                for side in (A, B):
                    info = side.get("team_info") or {}
                    if info.get("name"):
                        teams[info["name"]] = {"team": info["name"], "division": info.get("region") or "",
                                               "color": info.get("primaryColor") or ""}
                    for p in info.get("players") or []:
                        _remember(players, p, info.get("name", ""), sno)
                s1a = sum(A[k]["round_score"] for k in MATCHUPS)
                s1b = sum(B[k]["round_score"] for k in MATCHUPS)
                row.update(points_a=A["team_score"], points_b=B["team_score"], stage_one_a=s1a, stage_one_b=s1b,
                           golden_a=A["golden_game"]["score"], golden_b=B["golden_game"]["score"])
                for order, key in enumerate(MATCHUPS, 1):
                    a, b = A[key], B[key]
                    ap = [a.get("player")] if "player" in a else [a.get("playerA"), a.get("playerB")]
                    bp = [b.get("player")] if "player" in b else [b.get("playerA"), b.get("playerB")]
                    for p in ap + bp:
                        if p:
                            _remember(players, p, "", sno)
                    for g in (1, 2, 3):
                        pa, pb = a.get(f"gm_{g}"), b.get(f"gm_{g}")
                        if pa is None or pb is None or (pa == 0 and pb == 0):
                            continue
                        games.append({"season": sno, "match_id": m["id"], "date": m["date"], "order": order,
                                      "matchup": "doubles" if key.startswith("doubles") else key, "game": g,
                                      "team_a": ta, "team_b": tb,
                                      "a1": _pid(ap[0]), "a2": _pid(ap[1]) if len(ap) > 1 else "",
                                      "b1": _pid(bp[0]), "b2": _pid(bp[1]) if len(bp) > 1 else "",
                                      "points_a": pa, "points_b": pb})
                for side, other, team, opp, lead in ((A, B, ta, tb, s1a - s1b), (B, A, tb, ta, s1b - s1a)):
                    gg = side["golden_game"]
                    for p in gg.get("players") or []:
                        _remember(players, p, "", sno)
                    for pid, won in (gg.get("playerScores") or {}).items():
                        golden.append({"season": sno, "match_id": m["id"], "date": m["date"], "team": team,
                                       "opponent": opp, "head_start": max(lead, 0), "score": gg["score"],
                                       "opp_score": other["golden_game"]["score"], "player": pid,
                                       "rallies_won": int(won or 0)})
            matches.append(row)
    return matches, games, golden


def _remember(players: dict, p: dict, team: str, season: int) -> None:
    pid = p.get("id")
    if not pid:
        return
    cur = players.get(pid, {"player_id": pid, "team": "", "last_season": 0})
    cur.update({"name": p.get("name") or cur.get("name", ""), "gender": p.get("gender") or cur.get("gender", ""),
                "mltt_rating": p.get("mlttRating") or cur.get("mltt_rating", ""),
                "spindex_id": p.get("spindexId") or cur.get("spindex_id", ""),
                "hand": p.get("playingHand") or cur.get("hand", ""),
                "citizenship": p.get("citizenship") or cur.get("citizenship", "")})
    if team and season >= int(cur.get("last_season") or 0):
        cur["team"], cur["last_season"] = team, season
    players[pid] = cur


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def fetch(model_dir: Path, offline: bool = False, scheduled: bool = False) -> list[str]:
    data = Path(model_dir) / "data"
    f = Fetcher(data / "raw" / "mltt", offline)
    today = dt.date.today()
    seasons = sorted((s for s in f.get("/seasons") if _season_no(s["seasonName"]) >= 2),
                     key=lambda s: _season_no(s["seasonName"]))
    current = max(_season_no(s["seasonName"]) for s in seasons)
    keep = {_season_no(s["seasonName"]) for s in seasons}
    if scheduled:
        keep = {current}
    players = {r["player_id"]: r for r in _read(data / "players.csv")}
    teams = {r["team"]: r for r in _read(data / "teams.csv")}
    old = {name: [r for r in _read(data / name) if int(r["season"]) not in keep]
           for name in ("matches.csv", "games.csv", "golden.csv")}
    matches, games, golden = old["matches.csv"], old["games.csv"], old["golden.csv"]
    for s in seasons:
        if _season_no(s["seasonName"]) in keep:
            m, g, gg = season_rows(f, s, players, teams, today)
            matches += m
            games += g
            golden += gg
    key = lambda r: (int(r["season"]), r.get("start") or r["date"], r["match_id"])
    matches.sort(key=key)
    order = {r["match_id"]: i for i, r in enumerate(matches)}
    games.sort(key=lambda r: (order.get(r["match_id"], 0), int(r["order"]), int(r["game"])))
    golden.sort(key=lambda r: (order.get(r["match_id"], 0), r["team"], r["player"]))

    # check our current-season totals against the league's own standings
    check = []
    try:
        standings = f.get("/standings")
        mine: dict[str, list[int]] = {}
        for r in matches:
            if int(r["season"]) == current and r["status"] == "final" and r["stage"] == "regular":
                for t, pf, pa in ((r["team_a"], r["points_a"], r["points_b"]), (r["team_b"], r["points_b"], r["points_a"])):
                    acc = mine.setdefault(t, [0, 0])
                    acc[0] += int(pf)
                    acc[1] += int(pa)
        for t in standings:
            got = mine.get(t["name"], [0, 0])
            if got != [t["pointsFor"], t["pointsAgainst"]]:
                check.append(f"{t['name']}: ours {got}, league {[t['pointsFor'], t['pointsAgainst']]}")
            teams.setdefault(t["name"], {"team": t["name"], "division": t.get("region", ""), "color": t.get("color", "")})
            teams[t["name"]]["division"] = t.get("region") or teams[t["name"]].get("division", "")
    except Exception as exc:  # standings are only a check
        check.append(f"standings unavailable: {exc}")

    # SPINDEX rating histories: the rating each player had before any date (no hindsight)
    history, missing = [], []
    for pl in sorted(players.values(), key=lambda r: r.get("spindex_id") or ""):
        sid = pl.get("spindex_id")
        if not sid:
            continue
        try:
            rows = f.get(SPINDEX.format(id=urllib.parse.quote(sid)))
        except Exception:
            missing.append(sid)
            continue
        for h in rows or []:
            history.append({"spindex_id": sid, "date": h.get("date") or "", "old_rating": h.get("oldRating"),
                            "new_rating": h.get("newRating"), "event": h.get("eventName") or "",
                            "created": h.get("createdAt") or ""})
    history.sort(key=lambda r: (r["spindex_id"], r["date"], r["created"]))
    if missing:
        check.append(f"no SPINDEX history for {len(missing)} players: {', '.join(missing[:10])}")
    _write(data / "ratings_history.csv", HISTORY_COLS, history)

    _write(data / "matches.csv", MATCH_COLS, matches)
    _write(data / "games.csv", GAME_COLS, games)
    _write(data / "golden.csv", GOLDEN_COLS, golden)
    _write(data / "players.csv", PLAYER_COLS, sorted(players.values(), key=lambda r: r.get("name", "")))
    _write(data / "teams.csv", ["team", "division", "color"], sorted(teams.values(), key=lambda r: (r["division"], r["team"])))
    final = [r for r in matches if r["status"] == "final"]
    meta = {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "current_season": current,
            "source": "web.mltt.com/api (MLTT's results site); spindex.mltt.com (SPINDEX rating histories)",
            "rating_history_rows": len(history), "matches": len(matches), "final": len(final),
            "games": len(games), "players": len(players), "requests": f.requests,
            "last_result": max((r["date"] for r in final), default=""), "standings_check": check or "matches league standings"}
    (data / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    lines = [f"mltt: {len(final)}/{len(matches)} matches played, {len(games)} games, {len(players)} players, "
             f"{f.requests} requests; last result {meta['last_result']}"]
    lines += [f"  standings check: {c}" for c in check] or ["  standings check: matches the league's standings"]
    return lines
