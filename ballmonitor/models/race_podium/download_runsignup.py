"""Download multi-year race results across distances and field sizes from RunSignup.

Two downloads live here:

* `collect_race_data` (original, v0.5-0.7): top 150 finishers per edition of ~50 races,
  saved to data/runsignup/finishes.csv (also used by race_time). Because only the top 150
  overall were fetched, division field sizes in that file are truncated.
* `download_full_results` (v0.8): *every* finisher of each edition (all result pages),
  cached as gzipped JSON in data/raw/runsignup_full/ (gitignored). `build_division_panel`
  turns it into data/division_panel.csv (one row per race x distance x year x division with
  the true division field size and top-5 times) used by research.py.

    python -m ballmonitor.models.race_podium.download_runsignup --full [--max-races 200]
"""

from __future__ import annotations

import csv
import gzip
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RUNSIGNUP_API = "https://api.runsignup.com/rest"
DATA_DIR = Path(__file__).resolve().parent / "data" / "runsignup"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (ballmonitor running research; academic/open-source analysis)"}


def fetch_json(url: str, retries: int = 2, delay: float = 0.2) -> dict[str, Any] | None:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    return None


def parse_time_sec(val: str | None) -> float | None:
    if not val:
        return None
    val = val.strip().split(".")[0]  # strip fractional seconds
    parts = val.split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        sec = 0.0
        for p in parts:
            sec = sec * 60.0 + float(p)
        return sec if sec > 0 else None
    except ValueError:
        return None


# Events that are not comparable road-running results at a standard distance.
_EXCLUDE_EVENT = re.compile(r"virtual|\bmtb\b|bike|cycl|ultra|relay|walk only|kids?\b|\bdash\b")


def normalize_distance(name: str, dist_str: str | None) -> str:
    """Map an event name / distance string to 5k, 8k, 10k, 10mi, half, marathon or 'other'.

    Uses word boundaries so '15K' is not read as 5K, '1/2 Marathon' is a half, and
    virtual / bike / ultra / relay events are excluded.
    """
    t = f"{name} {dist_str or ''}".lower()
    if _EXCLUDE_EVENT.search(t):
        return "other"
    if re.search(r"\bhalf\b|1/2|13\.1", t):
        return "half"
    if re.search(r"marathon|26\.2", t):
        return "marathon"
    if re.search(r"(?<![\d.])10\s?k\b|10,000", t):
        return "10k"
    if re.search(r"(?<![\d.])10\s?(mi|mile|miler)\b", t):
        return "10mi"
    if re.search(r"(?<![\d.])8\s?k\b", t):
        return "8k"
    if re.search(r"(?<![\d.])5\s?k\b|(?<![\d.])3\.1\s?m", t):
        return "5k"
    return "other"


_METERS = {"5k": 5000.0, "8k": 8000.0, "10k": 10000.0, "10mi": 16093.44, "half": 21097.5, "marathon": 42195.0}
# Faster than this pace (s/mile) is not a real finish at 5K or longer (world records are ~4:00/mi+).
MIN_PLAUSIBLE_PACE_SEC_PER_MILE = 230.0
_DIST_TOKEN = re.compile(r"\d\s?k\b|mile|\bmi\b|marathon|1/2|13\.1|26\.2")


def clean_finishes(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Clean rows of finishes.csv before any analysis (the CSV itself is left as downloaded).

    1. Re-classify `distance_cat` from `event_name` with `normalize_distance` (the original
       download used substring matching: '15K' -> 5k, '1/2 Marathon' -> marathon, virtual and
       MTB events kept). If the event name has no distance token, the stored category is kept.
    2. Drop events classified 'other'.
    3. Drop finishes faster than MIN_PLAUSIBLE_PACE_SEC_PER_MILE (timing/category errors).
    4. Drop exact duplicates of (race, year, distance, person, chip time), and every copy of a
       (race, year, person, chip time) that appears under more than one distance (RunSignup
       returned the same result list for two events of at least one race).
    """
    out: list[dict[str, str]] = []
    for r in rows:
        ev = r.get("event_name", "") or ""
        cat = normalize_distance(ev, None)
        if cat == "other" and not _DIST_TOKEN.search(ev.lower()) and not _EXCLUDE_EVENT.search(ev.lower()):
            cat = r.get("distance_cat", "other")
        if cat not in _METERS:
            continue
        try:
            t_sec = float(r["chip_time_sec"])
        except (KeyError, ValueError):
            continue
        if t_sec / (_METERS[cat] / 1609.344) < MIN_PLAUSIBLE_PACE_SEC_PER_MILE:
            continue
        out.append({**r, "distance_cat": cat})

    def person(r: dict[str, str]) -> tuple[str, ...]:
        return (r["race_id"], str(r["year"]), (r.get("first_name") or "").strip().upper(),
                (r.get("last_name") or "").strip().upper(), str(r["chip_time_sec"]))

    dists: dict[tuple[str, ...], set[str]] = {}
    for r in out:
        dists.setdefault(person(r), set()).add(r["distance_cat"])
    seen: set[tuple[str, ...]] = set()
    cleaned = []
    for r in out:
        k = (*person(r), r["distance_cat"])
        if k in seen or len(dists[person(r)]) > 1:
            continue
        seen.add(k)
        cleaned.append(r)
    return cleaned


def discover_races(limit_per_keyword: int = 25) -> list[dict[str, Any]]:
    keywords = [
        "5k", "10k", "half marathon", "marathon", "turkey trot",
        "spring", "autumn", "fall", "classic", "memorial", "trail", "jingle", "clover"
    ]
    seen_ids = set()
    races = []

    print(f"Searching RunSignup for multi-year races across {len(keywords)} keywords...")
    for kw in keywords:
        url = f"{RUNSIGNUP_API}/races?format=json&results_per_page={limit_per_keyword}&has_results=T&name={urllib.parse.quote(kw)}"
        data = fetch_json(url)
        if not data or "races" not in data:
            continue
        for item in data["races"]:
            r = item["race"]
            r_id = r["race_id"]
            if r_id not in seen_ids:
                seen_ids.add(r_id)
                races.append({
                    "race_id": r_id,
                    "name": r["name"],
                    "last_date": r.get("last_date"),
                })
    print(f"Total candidate races found: {len(races)}")
    return races


def collect_race_data(max_races_to_download: int = 80) -> list[dict[str, Any]]:
    """Discover races and fetch multi-year results across divisions."""
    candidate_races = discover_races(limit_per_keyword=25)

    all_finishes = []
    races_with_multi_years = 0

    results_file = DATA_DIR / "finishes.csv"
    editions_file = DATA_DIR / "editions.csv"

    # Load existing finishes if present to allow incremental fetching
    existing_race_ids = set()
    if results_file.exists():
        with open(results_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_race_ids.add(int(row["race_id"]))
        print(f"Loaded {len(existing_race_ids)} previously cached races.")

    fieldnames = [
        "race_id", "race_name", "distance_cat", "year", "event_id", "event_name",
        "place", "first_name", "last_name", "gender", "age", "chip_time_sec", "chip_time_str"
    ]

    new_finishes_count = 0

    with open(results_file, "a" if existing_race_ids else "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        if not existing_race_ids:
            writer.writeheader()

        for idx, r_meta in enumerate(candidate_races, 1):
            if races_with_multi_years >= max_races_to_download:
                break

            r_id = r_meta["race_id"]
            if r_id in existing_race_ids:
                races_with_multi_years += 1
                continue

            # Fetch race detail to see all historical events
            detail_url = f"{RUNSIGNUP_API}/race/{r_id}?format=json"
            r_detail = fetch_json(detail_url)
            if not r_detail or "race" not in r_detail:
                continue

            events = r_detail["race"].get("events", [])
            # Group events by normalized distance category and extract years
            events_by_dist: dict[str, dict[int, dict[str, Any]]] = {}

            for e in events:
                st = e.get("start_time")
                if not st:
                    continue
                # Extract 4-digit year from start_time (e.g. 11/3/2023 10:30)
                year_match = re.search(r"\b(201[5-9]|202[0-6])\b", st)
                if not year_match:
                    continue
                yr = int(year_match.group(1))
                dist_cat = normalize_distance(e.get("name", ""), e.get("distance"))
                if dist_cat == "other":
                    continue

                if dist_cat not in events_by_dist:
                    events_by_dist[dist_cat] = {}
                # Keep earliest or primary event per year
                if yr not in events_by_dist[dist_cat]:
                    events_by_dist[dist_cat][yr] = e

            # Look for distance categories with >= 2 distinct years of events
            multi_year_dists = {d: y_map for d, y_map in events_by_dist.items() if len(y_map) >= 2}
            if not multi_year_dists:
                continue

            # Now fetch results for these events
            race_has_results = False
            for dist_cat, y_map in multi_year_dists.items():
                years_with_results = 0
                for yr, event in sorted(y_map.items()):
                    e_id = event["event_id"]
                    # Fetch results (top 150 finishers per edition)
                    res_url = f"{RUNSIGNUP_API}/race/{r_id}/results/get-results?format=json&event_id={e_id}&results_per_page=150"
                    res_data = fetch_json(res_url)
                    if not res_data or "individual_results_sets" not in res_data:
                        continue
                    rsets = res_data["individual_results_sets"]
                    if not rsets:
                        continue
                    results = rsets[0].get("results", [])
                    if len(results) < 10:
                        continue

                    years_with_results += 1
                    for item in results:
                        t_sec = parse_time_sec(item.get("chip_time") or item.get("clock_time"))
                        if not t_sec or t_sec < 60:
                            continue
                        g = (item.get("gender") or "").strip().upper()
                        if g not in ("M", "F"):
                            continue
                        try:
                            age = int(item.get("age") or 0)
                        except (ValueError, TypeError):
                            age = 0

                        row = {
                            "race_id": r_id,
                            "race_name": r_meta["name"],
                            "distance_cat": dist_cat,
                            "year": yr,
                            "event_id": e_id,
                            "event_name": event.get("name", ""),
                            "place": item.get("place", 0),
                            "first_name": (item.get("first_name") or "").strip(),
                            "last_name": (item.get("last_name") or "").strip(),
                            "gender": g,
                            "age": age,
                            "chip_time_sec": round(t_sec, 2),
                            "chip_time_str": item.get("chip_time") or item.get("clock_time"),
                        }
                        writer.writerow(row)
                        new_finishes_count += 1
                        all_finishes.append(row)

                if years_with_results >= 2:
                    race_has_results = True

            if race_has_results:
                races_with_multi_years += 1
                out_f.flush()
                print(f"[{races_with_multi_years}/{max_races_to_download}] Downloaded multi-year race {r_id}: {r_meta['name'][:40]} (new finishes: {new_finishes_count})")

    print(f"Data collection complete: {races_with_multi_years} multi-year races, {new_finishes_count} new finishes written to {results_file.name}")
    return all_finishes


# ---------------------------------------------------------------------------------------
# v0.8: full-field download + division panel
# ---------------------------------------------------------------------------------------

MODEL_DIR = Path(__file__).resolve().parent
RAW_FULL_DIR = MODEL_DIR / "data" / "raw" / "runsignup_full"
PANEL_CSV = MODEL_DIR / "data" / "division_panel.csv"
PAGE_SIZE = 2500
# An edition must have this many finishers to be kept (tiny result lists are often partial).
MIN_EDITION_FINISHERS = 30
# Distance categories must have results in at least this many years to be downloaded.
MIN_YEARS = 3

# Divisions written to the panel: open + standard non-overlapping 5-year brackets.
PANEL_DIVISIONS: list[tuple[str, str, int, int]] = [("M Open", "M", 0, 99), ("F Open", "F", 0, 99)] + [
    (f"{g} {lo}-{lo + 4}", g, lo, lo + 4) for g in ("M", "F") for lo in range(15, 75, 5)
] + [("M 75+", "M", 75, 99), ("F 75+", "F", 75, 99)]


def _discover_candidates(seed: int = 2026, pages: int = 12) -> list[dict[str, Any]]:
    """Race ids held in 2024-2025 whose names mention common road distances.

    The search API sorts by name, so pages are sampled at random (fixed seed) to avoid
    only taking races whose names start with digits or punctuation.
    """
    rng = random.Random(seed)
    keywords = ["5k", "10k", "half marathon", "marathon", "turkey trot", "8k", "10 mile", "road race", "run"]
    seen: dict[int, dict[str, Any]] = {}
    for kw in keywords:
        page_ids = sorted(rng.sample(range(1, 31), pages))
        for page in page_ids:
            url = (
                f"{RUNSIGNUP_API}/races?format=json&results_per_page=100&page={page}"
                f"&name={urllib.parse.quote(kw)}&start_date=2024-01-01&end_date=2025-12-31"
            )
            data = fetch_json(url)
            if not data or "races" not in data or not data["races"]:
                continue
            for item in data["races"]:
                r = item["race"]
                if _EXCLUDE_EVENT.search(r["name"].lower()):
                    continue
                seen.setdefault(int(r["race_id"]), {"race_id": int(r["race_id"]), "name": r["name"]})
    return list(seen.values())


def _plan_race(race_id: int) -> dict[str, Any] | None:
    """Pick one event per (distance, year) for a race; None if no distance has MIN_YEARS years."""
    detail = fetch_json(f"{RUNSIGNUP_API}/race/{race_id}?format=json")
    if not detail or "race" not in detail:
        return None
    race = detail["race"]
    by_dist: dict[str, dict[int, dict[str, Any]]] = {}
    for e in race.get("events", []):
        st = e.get("start_time") or ""
        m = re.search(r"\b(20[12]\d)\b", st)
        if not m:
            continue
        cat = normalize_distance(e.get("name", ""), e.get("distance"))
        if cat not in _METERS:
            continue
        # Several events of one distance in a year (e.g. elite + open waves) are ambiguous: skip that year.
        yr = int(m.group(1))
        slot = by_dist.setdefault(cat, {})
        ev = {"event_id": int(e["event_id"]), "name": e.get("name", ""), "start_time": st}
        slot[yr] = None if yr in slot else ev
    plan = {
        cat: {yr: ev for yr, ev in years.items() if ev is not None}
        for cat, years in by_dist.items()
    }
    plan = {cat: years for cat, years in plan.items() if len(years) >= MIN_YEARS}
    if not plan:
        return None
    state = (race.get("address") or {}).get("state", "")
    return {"race_id": race_id, "name": race.get("name", ""), "state": state, "events": plan}


def _fetch_event_results(race_id: int, event_id: int) -> list[list[Any]] | None:
    """All finishers of one event as [gender, age, chip_sec, first, last]; cached in RAW_FULL_DIR."""
    path = RAW_FULL_DIR / f"{race_id}_{event_id}.json.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    out: list[list[Any]] = []
    page = 1
    while True:
        url = (
            f"{RUNSIGNUP_API}/race/{race_id}/results/get-results?format=json&event_id={event_id}"
            f"&results_per_page={PAGE_SIZE}&page={page}"
        )
        data = fetch_json(url)
        if data is None:
            return None  # network failure: do not cache a partial list
        sets = data.get("individual_results_sets") or []
        if not sets:
            break
        rows = max(sets, key=lambda s: len(s.get("results") or [])).get("results") or []
        for item in rows:
            t = parse_time_sec(item.get("chip_time") or item.get("clock_time"))
            g = (item.get("gender") or "").strip().upper()
            try:
                age = int(item.get("age") or 0)
            except (TypeError, ValueError):
                age = 0
            if t and g in ("M", "F"):
                out.append([g, age, round(t, 1), (item.get("first_name") or "").strip(),
                            (item.get("last_name") or "").strip()])
        if len(rows) < PAGE_SIZE:
            break
        page += 1
    if not out:
        return out  # not cached: the edition may simply not have results yet
    RAW_FULL_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def download_full_results(max_races: int = 200, extra_race_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Download every finisher for multi-year races. Returns the race plans (also saved to races.json)."""
    RAW_FULL_DIR.mkdir(parents=True, exist_ok=True)
    index_path = RAW_FULL_DIR / "races.json"
    plans: dict[str, Any] = json.loads(index_path.read_text()) if index_path.exists() else {}

    ids: list[int] = list(extra_race_ids or [])
    if (DATA_DIR / "finishes.csv").exists():
        with open(DATA_DIR / "finishes.csv", newline="", encoding="utf-8") as f:
            ids += sorted({int(r["race_id"]) for r in csv.DictReader(f)})
    ids += [c["race_id"] for c in _discover_candidates()]
    ids = list(dict.fromkeys(ids))
    print(f"{len(ids)} candidate races; {len(plans)} already planned")

    n_ok = sum(1 for v in plans.values() if v)
    for rid in ids:
        if n_ok >= max_races:
            break
        if str(rid) in plans:
            continue
        plan = _plan_race(rid)
        plans[str(rid)] = plan
        if plan:
            n_ok += 1
            n_ev = sum(len(v) for v in plan["events"].values())
            print(f"[{n_ok}/{max_races}] {rid} {plan['name'][:50]}: {n_ev} events")
            for years in plan["events"].values():
                for ev in years.values():
                    res = _fetch_event_results(rid, ev["event_id"])
                    ev["finishers"] = len(res) if res is not None else None
        index_path.write_text(json.dumps(plans, indent=1))
    return [v for v in plans.values() if v]


def build_division_panel(path: Path = PANEL_CSV) -> int:
    """Build data/division_panel.csv from the cached full results.

    Cleaning per edition: drop finishes faster than MIN_PLAUSIBLE_PACE_SEC_PER_MILE, exact
    duplicate rows, editions with fewer than MIN_EDITION_FINISHERS, and editions whose raw
    result list (size and 20 fastest times) is identical to another distance's in the same
    race-year (RunSignup sometimes files one combined result list under two events). Division membership needs a known age (> 0); the open
    divisions count every finisher of that gender.

    Columns: race_id, race_name, state, distance, year, event_id, event_finishers,
    gender_finishers, division, gender, age_min, age_max, field_size, t1..t5 (seconds,
    blank if fewer finishers), boundary_prev (fastest same-gender finisher aged age_min-1
    in the previous calendar year's edition, blank if none).
    """
    index_path = RAW_FULL_DIR / "races.json"
    plans = {k: v for k, v in json.loads(index_path.read_text()).items() if v}
    rows_out: list[dict[str, Any]] = []
    for rid_s, plan in sorted(plans.items(), key=lambda kv: int(kv[0])):
        rid = int(rid_s)
        editions: dict[tuple[str, int], list[list[Any]]] = {}
        raw_sig: dict[tuple[str, int], tuple[Any, ...]] = {}
        for cat, years in plan["events"].items():
            for yr_s, ev in years.items():
                path_ev = RAW_FULL_DIR / f"{rid}_{ev['event_id']}.json.gz"
                if not path_ev.exists():
                    continue
                with gzip.open(path_ev, "rt", encoding="utf-8") as f:
                    res = json.load(f)
                raw_sig[(cat, int(yr_s))] = (len(res), tuple(sorted(float(r[2]) for r in res)[:20]))
                miles = _METERS[cat] / 1609.344
                seen: set[tuple[Any, ...]] = set()
                clean = []
                for g, age, t, fn, ln in res:
                    if t / miles < MIN_PLAUSIBLE_PACE_SEC_PER_MILE:
                        continue
                    k = (g, age, t, fn.upper(), ln.upper())
                    if k in seen:
                        continue
                    seen.add(k)
                    clean.append((g, int(age), float(t)))
                if len(clean) >= MIN_EDITION_FINISHERS:
                    editions[(cat, int(yr_s))] = clean
        # Drop result lists duplicated across distances within a race-year (compared on the
        # raw list, before the pace filter treats the copies differently)
        sig: dict[tuple[Any, ...], list[tuple[str, int]]] = {}
        for (cat, yr), rs in raw_sig.items():
            sig.setdefault((yr, rs), []).append((cat, yr))
        for keys in sig.values():
            if len(keys) > 1:
                for k in keys:
                    editions.pop(k, None)

        for (cat, yr), res in sorted(editions.items()):
            ev = plan["events"][cat][str(yr)]
            prev = editions.get((cat, yr - 1))
            for div, g, lo, hi in PANEL_DIVISIONS:
                is_open = lo == 0 and hi == 99
                times = sorted(t for gg, a, t in res if gg == g and (is_open or lo <= a <= hi))
                if not times:
                    continue
                bprev = ""
                if prev is not None and not is_open:
                    cands = [t for gg, a, t in prev if gg == g and a == lo - 1]
                    bprev = round(min(cands), 1) if cands else ""
                rows_out.append({
                    "race_id": rid, "race_name": plan["name"], "state": plan.get("state", ""),
                    "distance": cat, "year": yr, "event_id": ev["event_id"],
                    "event_finishers": len(res), "gender_finishers": sum(1 for gg, _, _ in res if gg == g),
                    "division": div, "gender": g, "age_min": lo, "age_max": hi,
                    "field_size": len(times),
                    **{f"t{i}": (round(times[i - 1], 1) if len(times) >= i else "") for i in range(1, 6)},
                    "boundary_prev": bprev,
                })
    fields = ["race_id", "race_name", "state", "distance", "year", "event_id", "event_finishers",
              "gender_finishers", "division", "gender", "age_min", "age_max", "field_size",
              "t1", "t2", "t3", "t4", "t5", "boundary_prev"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)
    return len(rows_out)


if __name__ == "__main__":
    import sys

    if "--full" in sys.argv:
        n = int(sys.argv[sys.argv.index("--max-races") + 1]) if "--max-races" in sys.argv else 200
        download_full_results(max_races=n)
        print(f"wrote {build_division_panel()} rows to {PANEL_CSV}")
    else:
        collect_race_data(max_races_to_download=40)
