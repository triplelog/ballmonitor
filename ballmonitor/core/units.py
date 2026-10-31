"""Parsing and formatting helpers shared across models (times, distances)."""

from __future__ import annotations

import re

METERS_PER_MILE = 1609.344
METERS_PER_KM = 1000.0

# Named distances, in meters. Keys are matched case-insensitively with spaces/underscores removed.
NAMED_DISTANCES = {
    "800m": 800.0,
    "1500m": 1500.0,
    "mile": METERS_PER_MILE,
    "1mi": METERS_PER_MILE,
    "3k": 3000.0,
    "2mi": 2 * METERS_PER_MILE,
    "5k": 5000.0,
    "8k": 8000.0,
    "5mi": 5 * METERS_PER_MILE,
    "10k": 10000.0,
    "15k": 15000.0,
    "10mi": 10 * METERS_PER_MILE,
    "20k": 20000.0,
    "half": 21097.5,
    "halfmarathon": 21097.5,
    "25k": 25000.0,
    "30k": 30000.0,
    "marathon": 42195.0,
    "50k": 50000.0,
    "50mi": 50 * METERS_PER_MILE,
    "100k": 100000.0,
}

_LABELS = {
    METERS_PER_MILE: "Mile",
    5000.0: "5K",
    8000.0: "8K",
    10000.0: "10K",
    15000.0: "15K",
    10 * METERS_PER_MILE: "10 mi",
    21097.5: "Half marathon",
    42195.0: "Marathon",
    50000.0: "50K",
}


def parse_time(value: str | int | float) -> float:
    """'1:32:00' -> 5520.0 seconds; '20:00' -> 1200.0; numbers are taken as seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"cannot parse time {value!r}; use h:mm:ss, m:ss or seconds")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds: float) -> str:
    """5520 -> '1:32:00'; 1200 -> '20:00'; 75.4 -> '1:15'."""
    total = round(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_distance(value: str | int | float) -> float:
    """'5k' / 'half' / 'marathon' / '10mi' / '3000m' / 3000 -> meters."""
    if isinstance(value, (int, float)):
        return float(value)
    key = re.sub(r"[\s_\-]", "", value.lower())
    if key in NAMED_DISTANCES:
        return NAMED_DISTANCES[key]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(m|km|k|mi|miles?)", key)
    if not match:
        raise ValueError(
            f"cannot parse distance {value!r}; use e.g. 5k, 10mi, 3000m, half, marathon, or meters"
        )
    number, unit = float(match.group(1)), match.group(2)
    if unit == "m":
        return number
    if unit in ("k", "km"):
        return number * METERS_PER_KM
    return number * METERS_PER_MILE


def distance_label(meters: float) -> str:
    for d, label in _LABELS.items():
        if abs(meters - d) < 0.5:
            return label
    if meters >= 1000:
        return f"{meters / 1000:g} km"
    return f"{meters:g} m"
