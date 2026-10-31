"""Build data/backtest.csv and data/demographic_priors.json from dated RunSignup results.

    python -m ballmonitor.models.race_time.download     # once: fills data/raw/runsignup/
    python -m ballmonitor.models.race_time.pipeline     # rebuilds the two files in data/

Steps (all thresholds are module constants below and documented in MODEL.md):

1. Load every cached event (download.py) and keep finishes with a valid name, gender,
   age, the runner's own city + state, and a plausible pace.
2. Event QA: drop events with too few finishers, and every event whose result list is a
   copy of another event's (RunSignup sometimes attaches one list to two distances).
3. Link runners: same first + last name, gender, home city and state, and birth year
   (event year - age) within +/- 1. A cluster with two finishes in the same event, or two
   finishes on the same day, is a name collision or a duplicate and is dropped whole.
4. Walk-forward cases: a target finish is predicted from the runner's most recent
   `MAX_INPUTS` finishes run strictly before the target date and within
   `LOOKBACK_DAYS`. Scenarios: `cross_distance` (no input at the target distance) and
   `same_distance` (at least one). For each runner the latest eligible target of each
   scenario is found, ONE of them is kept (picked by hash), and then a reproducible hash
   sample of runners (`SAMPLE` per scenario) is written, so every row is a different
   runner (independent cases).
5. Split: each runner is assigned to `train` or `test` by a hash of their id, so the
   research study can choose settings on train and report on test.
6. Demographic slope priors are fit on TRAIN runners only (pairs of races at different
   distances within 120 days of each other), so test cases never inform the priors.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ballmonitor.models.race_time.download import RAW_DIR, STANDARD, classify_event, _event_date

DATA_DIR = Path(__file__).resolve().parent / "data"
BACKTEST_CSV = DATA_DIR / "backtest.csv"
PRIORS_JSON = DATA_DIR / "demographic_priors.json"

MIN_FINISHERS = 15            # smaller result lists are often partial or mis-entered
MIN_PACE_SEC_PER_MILE = 225.0  # faster than ~3:45/mi is a timing / distance error
MAX_PACE_SEC_PER_MILE = 960.0  # slower than 16:00/mi is walking; not a running prediction
MIN_AGE, MAX_AGE = 10, 90
MAX_INPUTS = 3
LOOKBACK_DAYS = 3 * 365
PRIOR_PAIR_MAX_DAYS = 120
TEST_SHARE = 0.5
BAD_NAME = re.compile(
    r"\b(?:anon\w*|guest|unknown|bandit|runner|participant|n/?a|test|tbd|none)\b", re.I)
# The full walk-forward set has >100k cases; a deterministic sample of runners keeps the
# committed CSV small and the backtest fast. Each sampled runner gives ONE case.
SAMPLE = {"cross_distance": 3000, "same_distance": 2000}

FIELDS = [
    "case_id", "scenario", "split", "entity_id", "gender", "age",
    *[f"race{i}_{k}" for i in range(1, MAX_INPUTS + 1) for k in ("distance", "time", "date", "year")],
    "target", "target_date", "target_year", "actual_time", "event_id",
]


@dataclass
class Finish:
    race_id: int
    event_id: int
    date: date
    distance: str
    meters: float
    first: str
    last: str
    gender: str
    age: int
    city: str
    state: str
    time_sec: float


def parse_clock(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    parts = s.split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        sec = 0.0
        for p in parts:
            sec = sec * 60.0 + float(p)
    except ValueError:
        return None
    return sec if sec > 0 else None


def fmt_clock(sec: float) -> str:
    s = int(round(sec))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def load_finishes(stats: Counter) -> list[Finish]:
    races_dir = RAW_DIR / "races"
    results_dir = RAW_DIR / "results"
    finishes: list[Finish] = []
    signatures: dict[tuple, list[int]] = defaultdict(list)
    per_event: dict[int, list[Finish]] = {}
    for rpath in sorted(races_dir.glob("*.json")):
        race = json.loads(rpath.read_text())
        for ev in race.get("events", []):
            dkey = classify_event(race.get("name", ""), ev.get("name") or "", ev.get("distance"))
            dt = _event_date(ev.get("start_time"))
            path = results_dir / f"{race['race_id']}_{ev['event_id']}.json.gz"
            if not dkey or not dt or not path.exists():
                continue
            with gzip.open(path, "rt") as f:
                rows = json.load(f)
            stats["events_downloaded"] += 1
            meters = STANDARD[dkey]
            evd = date.fromisoformat(dt)
            kept: list[Finish] = []
            seen: set[tuple] = set()
            for x in rows:
                stats["rows"] += 1
                fn = (x.get("first_name") or "").strip().upper()
                ln = (x.get("last_name") or "").strip().upper()
                g = (x.get("gender") or "").strip().upper()
                city = (x.get("city") or "").strip().upper()
                st = (x.get("state") or "").strip().upper()
                t = parse_clock(x.get("chip_time")) or parse_clock(x.get("clock_time"))
                try:
                    age = int(x.get("age") or 0)
                except (TypeError, ValueError):
                    age = 0
                if len(fn) < 2 or len(ln) < 2 or BAD_NAME.search(f"{fn} {ln}"):
                    stats["drop_name"] += 1
                    continue
                if g not in ("M", "F") or not (MIN_AGE <= age <= MAX_AGE) or not city or not st:
                    stats["drop_demographics"] += 1
                    continue
                if not t:
                    stats["drop_time"] += 1
                    continue
                pace = t / (meters / 1609.344)
                if not (MIN_PACE_SEC_PER_MILE <= pace <= MAX_PACE_SEC_PER_MILE):
                    stats["drop_pace"] += 1
                    continue
                key = (fn, ln, g, round(t))
                if key in seen:  # same person listed twice in one event
                    stats["drop_dup_in_event"] += 1
                    continue
                seen.add(key)
                kept.append(Finish(race["race_id"], ev["event_id"], evd, dkey, meters,
                                   fn, ln, g, age, city, st, t))
            if len(kept) < MIN_FINISHERS:
                stats["drop_small_event"] += 1
                continue
            sig = tuple(sorted((f.first, f.last, round(f.time_sec)) for f in kept)[:25])
            signatures[sig].append(ev["event_id"])
            per_event[ev["event_id"]] = kept
    dup_events = {e for ids in signatures.values() if len(ids) > 1 for e in ids}
    stats["drop_duplicate_list_events"] = len(dup_events)
    for eid, kept in per_event.items():
        if eid not in dup_events:
            finishes.extend(kept)
            stats["events_kept"] += 1
    stats["finishes_kept"] = len(finishes)
    return finishes


def link_runners(finishes: list[Finish], stats: Counter) -> dict[str, list[Finish]]:
    by_key: dict[tuple, list[Finish]] = defaultdict(list)
    for f in finishes:
        by_key[(f.first, f.last, f.gender, f.state, f.city)].append(f)
    runners: dict[str, list[Finish]] = {}
    for key, fs in by_key.items():
        if len(fs) < 2:
            continue
        fs.sort(key=lambda f: (f.date.year - f.age, f.date))
        clusters: list[list[Finish]] = []
        for f in fs:
            by = f.date.year - f.age
            for c in clusters:
                c_by = [x.date.year - x.age for x in c]
                if max(c_by + [by]) - min(c_by + [by]) <= 1:
                    c.append(f)
                    break
            else:
                clusters.append([f])
        for c in clusters:
            if len(c) < 2:
                continue
            events = Counter(f.event_id for f in c)
            days = Counter(f.date for f in c)
            if max(events.values()) > 1 or max(days.values()) > 1:
                stats["drop_collision_clusters"] += 1
                continue
            c.sort(key=lambda f: f.date)
            by = min(f.date.year - f.age for f in c)
            rid = "_".join([*key, str(by)]).replace(" ", "_")
            runners[rid] = c
    stats["linked_runners"] = len(runners)
    return runners


def split_of(entity_id: str) -> str:
    h = int(hashlib.sha256(entity_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < TEST_SHARE else "train"


def build_cases(runners: dict[str, list[Finish]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for rid in sorted(runners):
        fs = runners[rid]
        chosen: dict[str, tuple[Finish, list[Finish]]] = {}
        for j in range(len(fs) - 1, 0, -1):
            tgt = fs[j]
            prior = [f for f in fs[:j] if 0 < (tgt.date - f.date).days <= LOOKBACK_DAYS]
            if not prior:
                continue
            inputs = prior[-MAX_INPUTS:]
            scen = ("same_distance" if any(f.distance == tgt.distance for f in inputs)
                    else "cross_distance")
            if scen not in chosen:
                chosen[scen] = (tgt, inputs)
            if len(chosen) == 2:
                break
        for scen, (tgt, inputs) in sorted(chosen.items()):
            row: dict[str, Any] = {
                "scenario": scen, "split": split_of(rid), "entity_id": rid,
                "gender": tgt.gender, "age": tgt.age, "target": tgt.distance,
                "target_date": tgt.date.isoformat(), "target_year": tgt.date.year,
                "actual_time": fmt_clock(tgt.time_sec), "event_id": tgt.event_id,
            }
            for i in range(MAX_INPUTS):
                f = inputs[i] if i < len(inputs) else None
                row[f"race{i + 1}_distance"] = f.distance if f else ""
                row[f"race{i + 1}_time"] = fmt_clock(f.time_sec) if f else ""
                row[f"race{i + 1}_date"] = f.date.isoformat() if f else ""
                row[f"race{i + 1}_year"] = f.date.year if f else ""
            cases.append(row)
    # One case per runner (scenario picked by hash when both exist), then sample runners
    # by a salted hash so the selection is reproducible and unrelated to the train/test hash.
    def h(text: str) -> float:
        return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

    by_runner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cases:
        by_runner[c["entity_id"]].append(c)
    one = []
    for rid, cs in by_runner.items():
        cs.sort(key=lambda c: c["scenario"])
        one.append(cs[int(h("scenario:" + rid) * len(cs)) % len(cs)])
    cases = []
    for scen, n in SAMPLE.items():
        pool = sorted((c for c in one if c["scenario"] == scen),
                      key=lambda c: h("sample:" + c["entity_id"]))
        cases.extend(pool[:n])
    cases.sort(key=lambda r: (r["target_date"], r["entity_id"], r["scenario"]))
    for i, r in enumerate(cases, 1):
        r["case_id"] = f"case_{i:05d}"
    return cases


def get_age_bracket(age: int) -> str:
    if age < 25:
        return "<25"
    if age < 35:
        return "25-34"
    if age < 50:
        return "35-49"
    if age < 65:
        return "50-64"
    return "65+"


def compute_demographic_priors(runners: dict[str, list[Finish]]) -> dict[str, Any]:
    """Median pairwise Riegel slope per gender x age cohort, from TRAIN runners only.

    Each runner contributes the mean slope of their pairs (different distances, at least
    one doubling apart is not required, within PRIOR_PAIR_MAX_DAYS), so prolific runners
    do not dominate. The median is used because slopes have a heavy tail from races run
    below full effort. Cohorts are shrunk toward the global median with weight n/(n+25).
    """
    per_cohort: dict[str, list[float]] = defaultdict(list)
    allk: list[float] = []
    for rid, fs in runners.items():
        if split_of(rid) != "train":
            continue
        ks: list[float] = []
        ages: list[int] = []
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                a, b = fs[i], fs[j]
                if abs((b.date - a.date).days) > PRIOR_PAIR_MAX_DAYS or a.distance == b.distance:
                    continue
                k = math.log(b.time_sec / a.time_sec) / math.log(b.meters / a.meters)
                if 0.85 <= k <= 1.35:
                    ks.append(k)
                    ages.append((a.age + b.age) // 2)
        if ks:
            k_mean = sum(ks) / len(ks)
            cohort = f"{fs[0].gender}_{get_age_bracket(sorted(ages)[len(ages) // 2])}"
            per_cohort[cohort].append(k_mean)
            allk.append(k_mean)

    def med(v: list[float]) -> float:
        s = sorted(v)
        n = len(s)
        return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])

    def sd(v: list[float]) -> float:
        m = sum(v) / len(v)
        return math.sqrt(sum((x - m) ** 2 for x in v) / max(len(v) - 1, 1))

    g = med(allk)
    priors: dict[str, Any] = {
        "_note": "Built by pipeline.py from TRAIN-split runners only: median per-runner "
                 "Riegel slope over race pairs within 120 days.",
        "global": {"beta1": round(g, 4), "sigma_beta1": round(sd(allk), 4), "count": len(allk)},
    }
    for cohort in sorted(per_cohort):
        v = per_cohort[cohort]
        w = len(v) / (len(v) + 25.0)
        priors[cohort] = {
            "beta1": round(w * med(v) + (1 - w) * g, 4),
            "sigma_beta1": round(sd(v), 4) if len(v) > 1 else None,
            "count": len(v),
        }
    return priors


def build(verbose: bool = True) -> dict[str, Any]:
    stats: Counter = Counter()
    finishes = load_finishes(stats)
    runners = link_runners(finishes, stats)
    cases = build_cases(runners)
    priors = compute_demographic_priors(runners)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(BACKTEST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(cases)
    PRIORS_JSON.write_text(json.dumps(priors, indent=2) + "\n")
    stats["cases"] = len(cases)
    stats["case_runners"] = len({c["entity_id"] for c in cases})
    for scen in ("cross_distance", "same_distance"):
        for sp in ("train", "test"):
            stats[f"cases_{scen}_{sp}"] = sum(
                1 for c in cases if c["scenario"] == scen and c["split"] == sp)
    if verbose:
        for k, v in sorted(stats.items()):
            print(f"{k:32s} {v}")
        print(f"wrote {BACKTEST_CSV} and {PRIORS_JSON}")
    return dict(stats)


if __name__ == "__main__":
    build()
