"""Build Home Turf's game data: web/data/game.json.

    python -m ballmonitor.games.home_turf.build

Reads territories.toml (map), rules.toml (rules), Open WAR's seasons (models/open_war/data/seasons.csv),
the Lahman People table (names, birthplaces; Triple Play's raw copy) and the birthplace map's geocoding
(models/baseball_birthplaces/data/players.csv, to split California and Pennsylvania). Each territory's
roster is its natives with at least `min_seasons` seasons, best career Open WAR first, `roster_depth` deep,
written compactly (compact(); about half the size of plain records, same players and seasons).
"""

from __future__ import annotations

import csv
import json
import tomllib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAHMAN = ROOT / "games" / "triple_play" / "data" / "raw" / "lahman_csv"
SEASONS = ROOT / "models" / "open_war" / "data" / "seasons.csv"
GEO = ROOT / "models" / "baseball_birthplaces" / "data" / "players.csv"
OUT = HERE / "web" / "data" / "game.json"


def load_map() -> dict:
    m = tomllib.loads((HERE / "territories.toml").read_text())
    terr = m["territories"]
    problems = []
    for tid, t in terr.items():
        if t["region"] not in m["regions"]:
            problems.append(f"{tid}: unknown region {t['region']}")
        for kind in ("land", "sea"):
            for n in t.get(kind, []):
                if n not in terr:
                    problems.append(f"{tid}: unknown neighbour {n}")
                elif tid not in terr[n].get(kind, []):
                    problems.append(f"{tid} -> {n} ({kind}) is not mutual")
    for rid in m["regions"]:   # every region must be one connected piece (land or sea)
        mem = {tid for tid, t in terr.items() if t["region"] == rid}
        if not mem:
            problems.append(f"region {rid} has no territories")
            continue
        start = next(iter(mem))
        reach, todo = {start}, [start]
        while todo:
            t = todo.pop()
            for n in terr[t].get("land", []) + terr[t].get("sea", []):
                if n in mem and n not in reach:
                    reach.add(n)
                    todo.append(n)
        if reach != mem:
            problems.append(f"region {rid} is not connected: {sorted(mem - reach)} cut off")
    seen = {}
    for tid, t in terr.items():
        for mem in t["members"]:
            if mem in seen:
                problems.append(f"{mem} is in {seen[mem]} and {tid}")
            seen[mem] = tid
    if problems:
        raise ValueError("territories.toml: " + "; ".join(problems))
    return m


def compact(r: dict) -> dict:
    """A roster player in the file's compact form (engine.js prepare() expands it): n = name,
    b = birth year, s = [first year, WAR x 10, then per later season: years since the previous one,
    WAR x 10]. Career WAR is the sum of the seasons."""
    s = r["seasons"]
    flat = [s[0][0], round(s[0][1] * 10)]
    for (y0, _), (y, w) in zip(s, s[1:]):
        flat += [y - y0, round(w * 10)]
    return {"n": r["name"], "b": int(r["born"]) if str(r["born"]).isdigit() else 0, "s": flat}


def member_of(person: dict, geo: dict) -> str:
    c, s = person["birthCountry"], person["birthState"]
    if c != "USA":
        return c
    if s == "CA" and geo:
        return "CA-S" if float(geo["lat"]) < 35.8 else "CA-N"
    if s == "PA" and geo:
        return "PA-W" if float(geo["lon"]) < -77.5 else "PA-E"
    return s


def build() -> dict:
    m = load_map()
    rules = tomllib.loads((HERE / "rules.toml").read_text())
    where = {mem: tid for tid, t in m["territories"].items() for mem in t["members"]}
    seasons = defaultdict(list)
    with SEASONS.open(newline="") as fh:
        for r in csv.DictReader(fh):
            seasons[r["playerID"]].append((int(r["yearID"]), round(float(r["WAR"]), 1)))
    with GEO.open(newline="") as fh:
        geo = {r["playerID"]: r for r in csv.DictReader(fh)}
    rosters = defaultdict(list)
    unplaced = defaultdict(int)
    with (LAHMAN / "People.csv").open(newline="", encoding="utf-8-sig") as fh:
        for p in csv.DictReader(fh):
            ss = sorted(seasons.get(p["playerID"], []))
            if len(ss) < rules["min_seasons"]:
                continue
            mem = member_of(p, geo.get(p["playerID"]))
            tid = where.get(mem)
            if tid is None:
                unplaced[mem or "(no birthplace)"] += 1
                continue
            rosters[tid].append({"id": p["playerID"], "name": f"{p['nameFirst']} {p['nameLast']}".strip(),
                                 "born": p["birthYear"], "city": p["birthCity"], "war": round(sum(w for _, w in ss), 1),
                                 "seasons": ss})
    for tid in rosters:
        rosters[tid].sort(key=lambda r: -r["war"])
        rosters[tid] = [compact(r) for r in rosters[tid][: rules["roster_depth"]]]
    territories = [{"id": tid, "name": t["name"], "region": t["region"], "x": t["x"], "y": t["y"],
                    "land": t.get("land", []), "sea": t.get("sea", []), "members": t["members"],
                    **({"bend": t["bend"]} if t.get("bend") else {})}
                   for tid, t in m["territories"].items()]
    game = {"version": 2, "rules": rules, "regions": m["regions"], "territories": territories, "rosters": rosters,
            "source": "Open WAR (models/open_war) from the Lahman Baseball Database (CC BY-SA 3.0)"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(game, separators=(",", ":")))
    return {"territories": len(territories), "players": sum(len(v) for v in rosters.values()),
            "unplaced": dict(sorted(unplaced.items(), key=lambda kv: -kv[1])[:8]), "kb": OUT.stat().st_size // 1024,
            "depth": {tid: round(sum(sum(r["s"][1::2]) / 10 for r in rosters[tid][:10])) for tid in m["territories"]}}


if __name__ == "__main__":
    info = build()
    print(f"{info['territories']} territories, {info['players']} players, {info['kb']} KB")
    print("not on the map:", info["unplaced"])
    print("top-10 career WAR per territory:", sorted(info["depth"].items(), key=lambda kv: kv[1]))
