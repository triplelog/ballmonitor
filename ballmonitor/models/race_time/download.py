"""Download dated RunSignup results for the race_time backtest (cached in data/raw/).

    python -m ballmonitor.models.race_time.download            # resumable; ~30-60 min first run
    python -m ballmonitor.models.race_time.download --states OH,PA --years 2018-2025

Unlike the race_podium export (top 150 finishers, year only, race location only), this
keeps every finisher, the event *date*, and each runner's self-reported city/state, which
is what lets pipeline.py link runners strictly and build walk-forward cases (input races
strictly before the target race).

Raw API responses are cached one file per event under data/raw/runsignup/, so re-running
only fetches what is missing. Nothing here is used at prediction time.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

API = "https://api.runsignup.com/rest"
HEADERS = {"User-Agent": "ballmonitor race_time research (open-source; polite, cached)"}
RAW_DIR = Path(__file__).resolve().parent / "data" / "raw" / "runsignup"

DEFAULT_STATES = ("OH",)
DEFAULT_YEARS = (2018, 2025)
WORKERS = 4
MIN_FINISHERS = 15

# Standard road distances (meters) the backtest keeps.
STANDARD = {
    "mile": 1609.344,
    "5k": 5000.0,
    "8k": 8000.0,
    "10k": 10000.0,
    "15k": 15000.0,
    "10mi": 16093.44,
    "half": 21097.5,
    "marathon": 42195.0,
}

# Events/races that are not comparable all-out road runs at a certified-ish distance.
EXCLUDE = re.compile(
    r"virtual|\bdiy\b|anywhere|trail|untimed|non-?timed|walker|relay|"
    r"\bkids?\b|youth|child|toddler|diaper|\bdogs?\b|canine|mutt|k-?9|ruck|bike|cycl|"
    r"duathlon|triathlon|aquathlon|swim|challenge|combo|\bdouble\b|\btriple\b|\bteams?\b|"
    r"stroller|wheelchair|hand ?cycle|ultra|cross country|\bxc\b|hill ?climb|stair|"
    r"obstacle|\bmud\b|\bcolou?r\b|glow|\bbeer\b|costume|pajama|snowshoe|\btrack\b|"
    r"indoor|treadmill|\bquarter\b|1/4|paddle|kayak|\brow(ing)?\b",
    re.I,
)

_lock = threading.Lock()
_last_call = [0.0]


def _get(url: str, retries: int = 3) -> dict[str, Any] | None:
    for attempt in range(retries):
        with _lock:  # global politeness: at most ~8 requests/second
            wait = 0.125 - (time.time() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2.0 * (attempt + 1))
        except Exception:
            time.sleep(2.0 * (attempt + 1))
    return None


def classify_event(race_name: str, event_name: str, distance: str | None) -> str | None:
    """Standard distance key for an event, or None if it is not a comparable road run."""
    text = f"{race_name} | {event_name}"
    if EXCLUDE.search(text):
        return None
    if re.search(r"\bwalk", event_name, re.I) and not re.search(r"\brun", event_name, re.I):
        return None
    meters = None
    m = re.match(r"\s*([\d.]+)\s*(k|km|kilometers?|m|mi|miles?|meters?)\b", (distance or "").lower())
    if m:
        v = float(m.group(1))
        unit = m.group(2)
        if unit in ("k", "km") or unit.startswith("kilom"):
            meters = v * 1000.0
        elif unit == "m" and v > 100 or unit.startswith("meter"):
            meters = v
        else:
            meters = v * 1609.344
    if meters is None:
        return None
    for key, ref in STANDARD.items():
        if abs(meters / ref - 1.0) <= 0.02:
            # The event name must not contradict the distance field
            ev = event_name.lower()
            if key != "half" and re.search(r"\bhalf\b|1/2|13\.1", ev):
                return None
            if key != "marathon" and key != "half" and re.search(r"marathon|26\.2", ev):
                return None
            return key
    return None


def _event_date(start_time: str | None) -> str | None:
    if not start_time:
        return None
    try:
        return datetime.strptime(start_time.split()[0], "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def search_races(state: str, year: int) -> list[dict[str, Any]]:
    """Races in `state` with results dated in `year` (searched month by month because
    the search endpoint stops after 1,000 hits)."""
    out: dict[int, dict[str, Any]] = {}
    for month in range(1, 13):
        last_day = 31 if month == 12 else (
            datetime(year, month + 1, 1) - datetime(year, month, 1)).days
        page = 1
        while True:
            q = urllib.parse.urlencode({
                "format": "json", "results_per_page": 250, "page": page, "state": state,
                "start_date": f"{year}-{month:02d}-01",
                "end_date": f"{year}-{month:02d}-{last_day:02d}",
                "only_races_with_results": "T",
            })
            data = _get(f"{API}/races?{q}")
            races = (data or {}).get("races", [])
            out.update((int(r["race"]["race_id"]), r["race"]) for r in races)
            if len(races) < 250:
                break
            page += 1
    return list(out.values())


def race_events(race_id: int) -> dict[str, Any] | None:
    path = RAW_DIR / "races" / f"{race_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = _get(f"{API}/race/{race_id}?format=json")
    if not data or "race" not in data:
        return None
    r = data["race"]
    keep = {
        "race_id": r["race_id"], "name": r.get("name", ""),
        "city": (r.get("address") or {}).get("city", ""),
        "state": (r.get("address") or {}).get("state", ""),
        "events": [
            {k: e.get(k) for k in ("event_id", "name", "start_time", "end_time", "distance")}
            for e in r.get("events", [])
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep))
    return keep


def event_results(race_id: int, event_id: int) -> list[dict[str, Any]]:
    path = RAW_DIR / "results" / f"{race_id}_{event_id}.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as f:
            return json.load(f)
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        data = _get(
            f"{API}/race/{race_id}/results/get-results?format=json&event_id={event_id}"
            f"&results_per_page=2500&page={page}"
        )
        sets = (data or {}).get("individual_results_sets") or []
        if not sets:
            break
        # The first set is the overall list; others are usually subsets (division lists).
        res = max(sets, key=lambda s: len(s.get("results") or [])).get("results") or []
        for x in res:
            rows.append({k: x.get(k) for k in (
                "result_id", "first_name", "last_name", "gender", "age", "city", "state",
                "chip_time", "clock_time")})
        if len(res) < 2500:
            break
        page += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(rows, f)
    return rows


def selected_events(race: dict[str, Any], y0: int, y1: int) -> list[dict[str, Any]]:
    out = []
    for e in race.get("events", []):
        date = _event_date(e.get("start_time"))
        if not date or not (y0 <= int(date[:4]) <= y1):
            continue
        end = _event_date(e.get("end_time"))
        if end and end != date:  # multi-day window = virtual / DIY event
            continue
        key = classify_event(race.get("name", ""), e.get("name") or "", e.get("distance"))
        if key:
            out.append({**e, "date": date, "distance_key": key})
    return out


def download(states: tuple[str, ...] = DEFAULT_STATES, years: tuple[int, int] = DEFAULT_YEARS) -> None:
    y0, y1 = years
    race_ids: set[int] = set()
    for st in states:
        for yr in range(y0, y1 + 1):
            found = search_races(st, yr)
            race_ids.update(int(r["race_id"]) for r in found)
            print(f"{st} {yr}: {len(found)} races with results (total {len(race_ids)})", flush=True)

    with ThreadPoolExecutor(WORKERS) as pool:
        races = [r for r in pool.map(race_events, sorted(race_ids)) if r]
    jobs = [(r["race_id"], e["event_id"]) for r in races for e in selected_events(r, y0, y1)]
    print(f"{len(races)} races, {len(jobs)} standard-distance events to fetch", flush=True)

    done = [0]

    def work(job: tuple[int, int]) -> None:
        event_results(*job)
        done[0] += 1
        if done[0] % 250 == 0:
            print(f"  {done[0]}/{len(jobs)} events", flush=True)

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(work, jobs))
    print("download complete", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", default=",".join(DEFAULT_STATES))
    ap.add_argument("--years", default=f"{DEFAULT_YEARS[0]}-{DEFAULT_YEARS[1]}")
    a = ap.parse_args()
    y0, y1 = (int(x) for x in a.years.split("-"))
    download(tuple(s.strip().upper() for s in a.states.split(",") if s.strip()), (y0, y1))


if __name__ == "__main__":
    main()
