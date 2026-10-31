"""Build the current-season data for ncaaf_bowls from ESPN's public APIs.

    ballmonitor fetch ncaaf_bowls [--offline]

Writes (all in data/):
  teams.json          every FBS team: ESPN conference, record to date, conference record,
                      FPI rating, last season's bowl, location/brand/APR carried from
                      data/team_profiles.csv
  schedule.json       every remaining regular-season game involving an FBS team (FCS
                      opponents included, conference title games excluded — the model
                      simulates those)
  results.json        every completed game (for audits and the results-only rating)
  ratings_fpi.csv     ESPN Football Power Index (points vs an average FBS team, neutral)
  ratings_results.csv results-only rating: ridge least squares on capped 2026 margins
  meta.json           season, snapshot time, sources, counts

Raw API responses are cached in data/raw/espn/ (gitignored); --offline rebuilds from that
cache. Uses only the standard library.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
FBS_GROUP = 80

# ESPN conference group id -> conference name used throughout the model.
CONFERENCES = {
    151: "AAC", 1: "ACC", 4: "Big 12", 5: "Big Ten", 12: "CUSA", 18: "Independent",
    15: "MAC", 17: "MWC", 9: "Pac-12", 8: "SEC", 37: "Sun Belt",
}

# The ten schools that left the Pac-12 in 2024 plus the two holdovers. In 2026 they still
# fill the Pac-12 "legacy" bowl slots (Alamo, Las Vegas, Holiday, Sun, Independence,
# Poinsettia) and are not part of their current conference's bowl selection.
LEGACY_PAC12 = {
    "usc", "ucla", "washington", "oregon", "utah", "colorado", "arizona", "arizona_state",
    "california", "stanford", "oregon_state", "washington_state",
}

# The 2026 Pac-12 ends with a flex week: ESPN lists "TBD at <home>" until the matchups are
# confirmed (six days before). Use the league's projected pairings (home team -> visitor);
# they are non-conference games. Source: pac-12.com, "The new Pac-12 announces its 2026
# football schedule" (2026-02-09), via fbschedules.com / CBS Sports.
FLEX_PROJECTED = {
    "utah_state": "boise_state", "washington_state": "oregon_state",
    "fresno_state": "san_diego_state", "colorado_state": "texas_state",
}

# ESPN display names that differ from the ids the model has always used.
ID_OVERRIDES = {
    "Miami": "miami", "Miami (OH)": "miami_oh", "Florida Atlantic": "florida_atlantic",
    "UL Monroe": "louisiana_monroe", "Florida International": "fiu", "Massachusetts": "umass",
    "Hawai'i": "hawaii", "San José State": "san_jose_state", "App State": "appalachian_state",
}


def _slug(name: str) -> str:
    if name in ID_OVERRIDES:
        return ID_OVERRIDES[name]
    out = "".join(c.lower() if c.isalnum() else "_" for c in name.replace("&", ""))
    return "_".join(p for p in out.split("_") if p)


class Fetcher:
    def __init__(self, raw_dir: Path, offline: bool):
        self.raw_dir = raw_dir
        self.offline = offline
        raw_dir.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, cache_name: str) -> Any:
        path = self.raw_dir / f"{cache_name}.json"
        if self.offline:
            if not path.exists():
                raise FileNotFoundError(f"--offline but {path} is not cached; run without --offline")
            return json.loads(path.read_text())
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ballmonitor/ncaaf_bowls"})
                with urllib.request.urlopen(req, timeout=30) as res:
                    data = json.loads(res.read())
                path.write_text(json.dumps(data))
                return data
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise AssertionError("unreachable")


def _https(ref: str) -> str:
    return ref.replace("http://", "https://")


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    data_dir = Path(model_dir) / "data"
    meta_in = json.loads((data_dir / "meta.json").read_text()) if (data_dir / "meta.json").exists() else {}
    season = int(meta_in.get("season", dt.date.today().year if dt.date.today().month >= 7 else dt.date.today().year - 1))
    f = Fetcher(data_dir / "raw" / "espn" / str(season), offline)
    log: list[str] = []

    # 1. Conferences and members (this season's alignment)
    conf_of: dict[str, str] = {}
    confs = f.get(f"{CORE}/seasons/{season}/types/2/groups/{FBS_GROUP}/children?limit=50", "conferences")
    for item in confs["items"]:
        gid = int(_https(item["$ref"]).split("/groups/")[1].split("?")[0])
        if gid not in CONFERENCES:
            raise ValueError(f"unknown ESPN conference id {gid}; add it to CONFERENCES")
        members = f.get(f"{CORE}/seasons/{season}/types/2/groups/{gid}/teams?limit=50", f"conf_{gid}_teams")
        for m in members["items"]:
            conf_of[_https(m["$ref"]).split("/teams/")[1].split("?")[0]] = CONFERENCES[gid]
    log.append(f"{len(conf_of)} FBS teams in {len(confs['items'])} conferences ({season})")

    # 2. Team names
    listing = f.get(f"{SITE}/teams?groups={FBS_GROUP}&limit=300", "teams")
    espn_name: dict[str, str] = {}
    for entry in listing["sports"][0]["leagues"][0]["teams"]:
        t = entry["team"]
        espn_name[t["id"]] = t["location"]
    missing = set(conf_of) - set(espn_name)
    for tid in missing:  # teams absent from the listing: look up individually
        espn_name[tid] = f.get(f"{SITE}/teams/{tid}", f"team_{tid}")["team"]["location"]
    ids = {tid: _slug(espn_name[tid]) for tid in conf_of}

    # 3. Every regular-season week (game results and remaining schedule)
    first = f.get(f"{SITE}/scoreboard?dates={season}&seasontype=2&week=1&groups={FBS_GROUP}&limit=400", "week_1")
    weeks = [int(e["value"]) for s in first["leagues"][0]["calendar"] if s["value"] == "2" for e in s["entries"]]
    events: dict[str, dict] = {}
    for wk in weeks:
        board = first if wk == 1 else f.get(
            f"{SITE}/scoreboard?dates={season}&seasontype=2&week={wk}&groups={FBS_GROUP}&limit=400", f"week_{wk}")
        for ev in board.get("events", []):
            ev["_week"] = wk
            events[ev["id"]] = ev

    results, schedule, skipped = [], [], []
    for ev in sorted(events.values(), key=lambda e: e["date"]):
        comp = ev["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = sides["home"]["team"], sides["away"]["team"]
        if home["id"] not in conf_of and away["id"] not in conf_of:
            continue
        notes = " ".join(n.get("headline", "") for n in comp.get("notes", []))
        flex = False
        if (away.get("location") == "TBD" and home["id"] in conf_of
                and ids[home["id"]] in FLEX_PROJECTED and "Championship" not in notes):
            visitor = FLEX_PROJECTED[ids[home["id"]]]
            away = {"id": next(t for t, i in ids.items() if i == visitor), "location": visitor}
            flex = True
        if "Championship" in notes or "TBD" in (home.get("location", ""), away.get("location", "")):
            skipped.append(f"{ev['name']} ({notes or 'TBD'})")  # conference title games are simulated
            continue
        status = comp["status"]["type"]
        if status.get("name") in ("STATUS_CANCELED", "STATUS_POSTPONED") and not status.get("completed"):
            skipped.append(f"{ev['name']} ({status['name']})")
            continue

        def ref(team: dict) -> str:
            return ids[team["id"]] if team["id"] in conf_of else f"fcs_{_slug(team['location'])}"

        game = {
            "home": ref(home), "away": ref(away),
            "neutral": bool(comp.get("neutralSite")),
            "conf": bool(comp.get("conferenceCompetition")) and not flex,
            "date": ev["date"][:10], "week": ev["_week"], "espn_id": ev["id"],
        }
        if flex:
            game["flex_projected"] = True
        if status.get("completed"):
            game["home_score"] = int(sides["home"]["score"])
            game["away_score"] = int(sides["away"]["score"])
            results.append(game)
        else:
            schedule.append(game)
    log.append(f"{len(results)} completed games, {len(schedule)} remaining; "
               f"{len(skipped)} title games/cancellations left out")

    # 4. ESPN FPI
    fpi: dict[str, float] = {}
    page = 1
    while True:
        res = f.get(f"{CORE}/seasons/{season}/powerindex?limit=200&page={page}", f"fpi_p{page}")
        for item in res["items"]:
            tid = _https(item["team"]["$ref"]).split("/teams/")[1].split("?")[0]
            vals = {p["name"]: p.get("value") for p in item["predictives"]}
            if tid in conf_of:
                fpi[ids[tid]] = round(float(vals["fpi"]), 2)
        if page >= res.get("pageCount", 1):
            break
        page += 1
    if missing_fpi := sorted(set(ids.values()) - set(fpi)):
        raise ValueError(f"no FPI for {missing_fpi}")
    fpi_updated = res["items"][0].get("lastUpdated", "") if res["items"] else ""
    log.append(f"FPI for {len(fpi)} teams (ESPN lastUpdated {fpi_updated})")

    # 5. Last season's bowls (repeat-bowl avoidance)
    bowls = json.loads((data_dir / "bowls.json").read_text())
    bowl_by_name = {b["espn_name"].lower(): b["id"] for b in bowls if b.get("espn_name")}
    for b in bowls:
        for alias in b.get("former_names", []):
            bowl_by_name[alias.lower()] = b["id"]
    last_bowl: dict[str, str] = {}
    post = f.get(f"{SITE}/scoreboard?dates={season - 1}&seasontype=3&groups={FBS_GROUP}&limit=400", "prev_postseason")
    for ev in post.get("events", []):
        comp = ev["competitions"][0]
        title = " ".join(n.get("headline", "") for n in comp.get("notes", [])).lower()
        bid = next((v for k, v in bowl_by_name.items() if k in title), None)
        if not bid:
            continue
        for c in comp["competitors"]:
            if c["team"]["id"] in conf_of:
                last_bowl[ids[c["team"]["id"]]] = bid

    # 6. Records from results
    rec = {tid: {"wins": 0, "losses": 0, "conf_wins": 0, "conf_losses": 0} for tid in ids.values()}
    for g in results:
        hw = g["home_score"] > g["away_score"]
        for team, won in ((g["home"], hw), (g["away"], not hw)):
            if team in rec:
                rec[team]["wins" if won else "losses"] += 1
                if g["conf"]:
                    rec[team]["conf_wins" if won else "conf_losses"] += 1

    # 7. Results-only rating
    params = _rating_params(Path(model_dir))
    fitted, fcs_rating = _fit_results_rating(results, set(ids.values()), params)

    # 8. Team file: carry location / brand / APR from the hand-maintained profile table
    profiles = _read_profiles(data_dir / "team_profiles.csv")
    teams, no_profile = [], []
    for tid, team_id in sorted(ids.items(), key=lambda kv: (conf_of[kv[0]], -fpi[kv[1]])):
        prof = profiles.get(team_id)
        if prof is None:
            no_profile.append(team_id)
            prof = {}
        teams.append({
            "id": team_id, "name": prof.get("name") or espn_name[tid], "espn_id": tid,
            "conf": conf_of[tid], "rating": fpi[team_id],
            "apr": int(prof["apr"]) if prof.get("apr") else 980,
            "brand": int(prof["brand"]) if prof.get("brand") else 4,
            "city": prof.get("city", ""), "state": prof.get("state", ""),
            "lat": float(prof["lat"]) if prof.get("lat") else 0.0,
            "lon": float(prof["lon"]) if prof.get("lon") else 0.0,
            **rec[team_id],
            "last_bowl": last_bowl.get(team_id),
            "legacy_pac12": team_id in LEGACY_PAC12,
        })
    if no_profile:
        raise ValueError(f"add these teams to data/team_profiles.csv (location, brand, APR): {no_profile}")

    # 9. Write
    (data_dir / "teams.json").write_text(json.dumps(teams, indent=1))
    (data_dir / "schedule.json").write_text(json.dumps(schedule, indent=1))
    (data_dir / "results.json").write_text(json.dumps(results, indent=1))
    _write_ratings(data_dir / "ratings_fpi.csv", "fpi", fpi)
    _write_ratings(data_dir / "ratings_results.csv", "results_rating", fitted)
    games_per_team: dict[str, int] = {}
    for g in results + schedule:
        for t in (g["home"], g["away"]):
            games_per_team[t] = games_per_team.get(t, 0) + 1
    counts = {t: games_per_team.get(t, 0) for t in ids.values()}
    meta = {
        "season": season,
        "snapshot_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "last_completed_game": max((g["date"] for g in results), default=None),
        "fpi_last_updated": fpi_updated,
        "teams": len(teams), "completed_games": len(results), "remaining_games": len(schedule),
        "regular_season_games_per_team": {"min": min(counts.values()), "max": max(counts.values())},
        "fcs_pooled_results_rating": round(fcs_rating, 1),
        "sources": {
            "conferences": f"{CORE}/seasons/{season}/types/2/groups/{FBS_GROUP}/children",
            "games": f"{SITE}/scoreboard?seasontype=2&week=N&groups={FBS_GROUP}",
            "ratings": f"{CORE}/seasons/{season}/powerindex",
            "last_bowl": f"{SITE}/scoreboard?dates={season - 1}&seasontype=3",
        },
    }
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    log.append(f"wrote teams.json, schedule.json, results.json, ratings_fpi.csv, ratings_results.csv, meta.json")
    log.append(f"regular-season games per team: {meta['regular_season_games_per_team']}; "
               f"FCS pooled rating {fcs_rating:+.1f}")
    return log


def _rating_params(model_dir: Path) -> dict[str, float]:
    import tomllib
    cfg = tomllib.loads((model_dir / "config.toml").read_text())["params"]
    return {k: float(cfg[k]["value"]) for k in ("home_field_points", "rating_margin_cap", "rating_ridge")}


def _fit_results_rating(results: list[dict], fbs: set[str], p: dict[str, float]) -> tuple[dict[str, float], float]:
    """Ridge least squares: margin = r_home - r_away + hfa*(not neutral), margins capped.

    FCS opponents share one pooled rating. Solved by Gauss-Seidel (no numpy needed).
    """
    cap, ridge, hfa = p["rating_margin_cap"], p["rating_ridge"], p["home_field_points"]
    key = lambda t: t if t in fbs else "FCS"  # noqa: E731
    teams = sorted(fbs) + ["FCS"]
    r = {t: 0.0 for t in teams}
    games = [(key(g["home"]), key(g["away"]),
              max(-cap, min(cap, g["home_score"] - g["away_score"])) - (0.0 if g["neutral"] else hfa))
             for g in results]
    by_team: dict[str, list[tuple[str, float]]] = {t: [] for t in teams}
    for h, a, m in games:
        by_team[h].append((a, m))
        by_team[a].append((h, -m))
    for _ in range(500):
        delta = 0.0
        for t in teams:
            gs = by_team[t]
            new = sum(r[o] + m for o, m in gs) / (len(gs) + ridge)
            delta = max(delta, abs(new - r[t]))
            r[t] = new
        mean = sum(r[t] for t in fbs) / len(fbs)  # center on the average FBS team
        for t in teams:
            r[t] -= mean
        if delta < 1e-6:
            break
    return {t: round(r[t], 2) for t in sorted(fbs)}, r["FCS"]


def _read_profiles(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


def _write_ratings(path: Path, column: str, ratings: dict[str, float]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["team", column])
        for t, v in sorted(ratings.items(), key=lambda kv: -kv[1]):
            w.writerow([t, v])
