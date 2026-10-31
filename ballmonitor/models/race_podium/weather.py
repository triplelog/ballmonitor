"""Weather lookup and climatological variance estimation for race_podium.

Uses Open-Meteo archive and forecast APIs with local caching in data/runsignup/weather_cache.json
and geocodes US cities using ballmonitor/models/ncaaf_recruiting/data/reference/uscities.csv.
"""

from __future__ import annotations

import csv
import json
import math
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

CACHE_FILE = Path(__file__).resolve().parent / "data" / "runsignup" / "weather_cache.json"
US_CITIES_CSV = (
    Path(__file__).resolve().parents[1]
    / "ncaaf_recruiting"
    / "data"
    / "reference"
    / "uscities.csv"
)

_CITY_COORDS: dict[tuple[str, str], tuple[float, float]] = {}


def _load_city_coords() -> dict[tuple[str, str], tuple[float, float]]:
    global _CITY_COORDS
    if _CITY_COORDS:
        return _CITY_COORDS

    if US_CITIES_CSV.exists():
        with open(US_CITIES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                city = row["city"].strip().lower()
                state = row["state_id"].strip().upper()
                try:
                    lat = float(row["lat"])
                    lng = float(row["lng"])
                    key = (city, state)
                    if key not in _CITY_COORDS:
                        _CITY_COORDS[key] = (lat, lng)
                except ValueError:
                    continue
    return _CITY_COORDS


def geocode_city_state(city: str, state: str) -> tuple[float, float] | None:
    coords = _load_city_coords()
    return coords.get((city.strip().lower(), state.strip().upper()))


def _read_cache() -> dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_weather(lat: float, lng: float, date_str: str) -> dict[str, Any]:
    """Fetch morning race conditions (temperature, dew point, wind) for a given date.

    Uses Open-Meteo archive for past dates and forecast for near-future dates.
    Results are cached locally.
    """
    cache = _read_cache()
    cache_key = f"{lat:.2f},{lng:.2f}:{date_str}"
    if cache_key in cache:
        return cache[cache_key]

    parsed_date = date.fromisoformat(date_str)
    today = date.today()
    days_diff = (parsed_date - today).days

    if days_diff > 16:
        # Date is too far in future for forecast API; return None to signal climatology
        return {"source": "climatology"}

    if days_diff < -2:
        # Past date: use historical archive API
        base_url = "https://archive-api.open-meteo.com/v1/archive"
    else:
        # Near past or future forecast within 16 days
        base_url = "https://api.open-meteo.com/v1/forecast"

    url = (
        f"{base_url}?latitude={lat:.4f}&longitude={lng:.4f}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&hourly=temperature_2m,dew_point_2m,wind_speed_10m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ballmonitor running research)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            hourly = data.get("hourly", {})
            # Morning race hours 8:00 AM to 11:00 AM (indices 8, 9, 10)
            t_slice = hourly.get("temperature_2m", [])[8:11] or hourly.get("temperature_2m", [])[:3]
            dp_slice = hourly.get("dew_point_2m", [])[8:11] or hourly.get("dew_point_2m", [])[:3]
            w_slice = hourly.get("wind_speed_10m", [])[8:11] or hourly.get("wind_speed_10m", [])[:3]

            if not t_slice:
                return {"source": "climatology"}

            result = {
                "temp_f": round(sum(t_slice) / len(t_slice), 1),
                "dew_point_f": round(sum(dp_slice) / len(dp_slice), 1),
                "wind_mph": round(sum(w_slice) / len(w_slice), 1),
                "source": "archive" if days_diff < -2 else "forecast",
            }
            cache[cache_key] = result
            _write_cache(cache)
            return result
    except Exception:
        return {"source": "climatology"}
