"""Load ESPN college football game summaries (bundled, cached, or downloaded).

ESPN's site API is public but unofficial and undocumented; it can change without notice.

Lookup order for a game id:
  1. data/games/<id>.json        trimmed summaries bundled with the model (committed)
  2. data/raw/summary_<id>.json  full responses cached from earlier downloads (gitignored)
  3. the network (only when allowed); completed games are written to the cache

Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
SUMMARY_URL = SITE + "/summary?event={id}"
SCOREBOARD_URL = SITE + "/scoreboard?dates={date}&groups=80&limit=300"
USER_AGENT = "ballmonitor-cfb_replay/0.1 (personal use)"


def games_dir(model_dir: Path) -> Path:
    return model_dir / "data" / "games"


def raw_dir(model_dir: Path) -> Path:
    return model_dir / "data" / "raw"


def _get_json(url: str, timeout: float) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"ESPN returned HTTP {exc.code} for {url}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"could not reach ESPN ({exc}); try a bundled game or check the network") from None
    except json.JSONDecodeError:
        raise ValueError(f"ESPN returned something that is not JSON for {url}") from None


def is_summary(data: Any) -> bool:
    try:
        return bool(data["header"]["competitions"][0]["competitors"]) and "drives" in data
    except (KeyError, IndexError, TypeError):
        return False


def is_completed(data: dict) -> bool:
    try:
        return bool(data["header"]["competitions"][0]["status"]["type"]["completed"])
    except (KeyError, IndexError, TypeError):
        return False


def normalize_game_id(game: Any) -> str:
    text = str(game).strip()
    if not re.fullmatch(r"\d{6,12}", text):
        raise ValueError(f"game must be a numeric ESPN event id (e.g. 401858274), got {game!r}")
    return text


def load_summary(model_dir: Path, game_id: str, *, allow_network: bool, timeout: float) -> tuple[dict, str]:
    """Return (summary, where_it_came_from)."""
    bundled = games_dir(model_dir) / f"{game_id}.json"
    if bundled.exists():
        return json.loads(bundled.read_text(encoding="utf-8")), f"bundled data/games/{game_id}.json"
    cached = raw_dir(model_dir) / f"summary_{game_id}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8")), f"cached data/raw/summary_{game_id}.json"
    if not allow_network:
        raise ValueError(f"game {game_id} is not bundled or cached and allow_network is false")
    data = _get_json(SUMMARY_URL.format(id=game_id), timeout)
    if not is_summary(data):
        raise ValueError(f"ESPN has no game summary for event id {game_id}")
    if is_completed(data):
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data), encoding="utf-8")
    return data, "downloaded from ESPN summary API"


# ---------------------------------------------------------------------------------------
# Finding a game from team names + date


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def team_names(team: dict) -> list[str]:
    keys = ("displayName", "shortDisplayName", "location", "abbreviation", "name", "nickname")
    return [_norm(team.get(k)) for k in keys if team.get(k)]


def team_match_score(query: str, team: dict) -> int:
    """2 = exact match on a name field, 1 = all query words appear in the display name, 0 = no."""
    q = _norm(query)
    if not q:
        return 0
    names = team_names(team)
    if q in names:
        return 2
    display = _norm(team.get("displayName"))
    return 1 if all(w in display.split() for w in q.split()) else 0


def _event_teams(competition: dict) -> dict[str, dict]:
    return {c.get("homeAway"): c.get("team", {}) for c in competition.get("competitors", [])}


def _match_event(competition: dict, home: str, away: str) -> tuple[int, bool]:
    """(score, swapped). Score 0 = not this game."""
    teams = _event_teams(competition)
    h, a = teams.get("home", {}), teams.get("away", {})
    straight = min(team_match_score(home, h), team_match_score(away, a))
    swapped = min(team_match_score(home, a), team_match_score(away, h))
    if straight >= swapped:
        return straight, False
    return swapped, True


def local_dates(iso: str) -> set[str]:
    """Dates a kickoff time could be listed under (UTC date and US Eastern-ish date)."""
    try:
        when = dt.datetime.strptime(iso.replace("Z", ""), "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            when = dt.datetime.fromisoformat(iso.replace("Z", ""))
        except ValueError:
            return set()
    return {when.date().isoformat(), (when - dt.timedelta(hours=5)).date().isoformat()}


def find_game(model_dir: Path, home: str, away: str, date: str, *, allow_network: bool,
              timeout: float) -> tuple[str, str]:
    """Return (event_id, how_it_was_found)."""
    try:
        day = dt.date.fromisoformat(str(date))
    except ValueError:
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}") from None
    best: tuple[int, str, bool] | None = None
    for path in sorted(games_dir(model_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        comp = data["header"]["competitions"][0]
        if day.isoformat() not in local_dates(comp.get("date", "")):
            continue
        score, swapped = _match_event(comp, home, away)
        if score and (best is None or score > best[0]):
            best = (score, path.stem, swapped)
    if best:
        note = " (home/away were swapped)" if best[2] else ""
        return best[1], f"matched bundled game {best[1]}{note}"

    stamp = day.strftime("%Y%m%d")
    cached = raw_dir(model_dir) / f"scoreboard_{stamp}.json"
    if cached.exists():
        board = json.loads(cached.read_text(encoding="utf-8"))
    elif allow_network:
        board = _get_json(SCOREBOARD_URL.format(date=stamp), timeout)
        cached.parent.mkdir(parents=True, exist_ok=True)
        if day < dt.date.today():
            cached.write_text(json.dumps(board), encoding="utf-8")
    else:
        raise ValueError(f"no bundled game for {away} at {home} on {date}, and allow_network is false")
    found: list[tuple[int, str, bool, str]] = []
    for event in board.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        score, swapped = _match_event(comp, home, away)
        if score:
            found.append((score, str(event.get("id")), swapped, event.get("name", "")))
    if not found:
        raise ValueError(f"no FBS game found for {away} at {home} on {date}")
    found.sort(key=lambda f: -f[0])
    if len(found) > 1 and found[0][0] == found[1][0]:
        names = "; ".join(f[3] for f in found[:4])
        raise ValueError(f"team names are ambiguous on {date}: {names}. Pass the ESPN game id instead")
    score, event_id, swapped, name = found[0]
    note = " (home/away were swapped)" if swapped else ""
    return event_id, f"found {name} ({event_id}) on the {date} scoreboard{note}"


# ---------------------------------------------------------------------------------------
# Trimming a summary to what the model needs (for the bundled data/games/ files)

PLAY_KEYS = ("id", "sequenceNumber", "type", "text", "awayScore", "homeScore", "period", "clock",
             "scoringPlay", "isTurnover", "isPenalty", "statYardage", "scoringType")
END_KEYS = ("down", "distance", "yardLine", "yardsToEndzone", "possessionText", "team")
TEAM_KEYS = ("id", "location", "name", "nickname", "abbreviation", "displayName",
             "shortDisplayName", "color", "alternateColor")


def trim_summary(data: dict) -> dict:
    header = data["header"]
    comp = header["competitions"][0]
    competitors = []
    for c in comp["competitors"]:
        team = {k: c["team"][k] for k in TEAM_KEYS if k in c["team"]}
        logos = c["team"].get("logos") or []
        if logos:
            team["logos"] = [{"href": logos[0].get("href")}]
        competitors.append({
            **{k: c[k] for k in ("id", "homeAway", "winner", "score", "rank", "record") if k in c},
            "team": team,
        })
    drives = []
    for drive in data.get("drives", {}).get("previous", []):
        plays = []
        for play in drive.get("plays", []):
            slim = {k: play[k] for k in PLAY_KEYS if k in play}
            for side in ("start", "end"):
                slim[side] = {k: play.get(side, {})[k] for k in END_KEYS if k in play.get(side, {})}
            slim["teamParticipants"] = [
                {"id": t.get("id"), "type": t.get("type")} for t in play.get("teamParticipants", [])
            ]
            plays.append(slim)
        drives.append({k: drive.get(k) for k in ("id", "description", "result")} | {"plays": plays})
    venue = (data.get("gameInfo") or {}).get("venue") or {}
    pick = [
        {k: p.get(k) for k in ("provider", "details", "spread", "overUnder")}
        | {side: {k: (p.get(side) or {}).get(k) for k in ("moneyLine", "favorite")}
           for side in ("homeTeamOdds", "awayTeamOdds")}
        for p in (data.get("pickcenter") or [])[:1]
    ]
    for p in pick:
        p["provider"] = {"name": (p.get("provider") or {}).get("name")}
    return {
        "_note": "Trimmed ESPN college football summary (site.api.espn.com); personal use. "
                 "Rebuild with `ballmonitor fetch cfb_replay`.",
        "header": {
            "id": header.get("id"),
            "season": header.get("season"),
            "competitions": [{
                "id": comp.get("id"),
                "date": comp.get("date"),
                "neutralSite": comp.get("neutralSite"),
                "status": comp.get("status"),
                "competitors": competitors,
            }],
        },
        "gameInfo": {"venue": {"fullName": venue.get("fullName"), "address": venue.get("address")}},
        "drives": {"previous": drives},
        "winprobability": data.get("winprobability", []),
        "pickcenter": pick,
    }
