"""Environmental adjustments for race times: elevation gain/loss, altitude, weather, and GPX courses.

Physiological references:
- Minetti, A. E. et al. (2002). Energy cost of walking and running at extreme uphill and downhill gradients.
  Journal of Applied Physiology, 93(3), 1039-1046.
- Péronnet, F. et al. (1991). Modeling endurance running performance at altitude.
- Bassett, D. R. & Howley, E. T. (1997). Limiting factors for maximum oxygen uptake and determinants of endurance performance.
- Montain, S. J. et al. (2007). Impact of heat and hydration on marathon performance.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METERS_PER_FOOT = 0.3048


def parse_elevation(val: str | int | float | None) -> float:
    """Parse elevation string or number to meters (e.g. '500ft', '150m', 150 -> meters)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip().lower()
    match = re.fullmatch(r"([\-+]?\d+(?:\.\d+)?)\s*(m|meter|meters|ft|feet|foot)?", val_str)
    if not match:
        raise ValueError(f"cannot parse elevation {val!r}; use e.g. '600ft', '180m' or meters")
    num = float(match.group(1))
    unit = match.group(2) or "m"
    if unit in ("ft", "feet", "foot"):
        return num * METERS_PER_FOOT
    return num


def parse_temp(val: str | int | float | None) -> float | None:
    """Parse temperature to Fahrenheit (e.g. '75F', '24C', 75 -> float)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip().upper()
    match = re.fullmatch(r"([\-+]?\d+(?:\.\d+)?)\s*([FC])?", val_str)
    if not match:
        raise ValueError(f"cannot parse temperature {val!r}; use e.g. 75, '75F' or '24C'")
    num = float(match.group(1))
    unit = match.group(2) or "F"
    if unit == "C":
        return num * 9.0 / 5.0 + 32.0
    return num


def dew_point_from_humidity(temp_f: float, humidity_pct: float) -> float:
    """Approximate dew point (°F) from temperature (°F) and relative humidity (%).

    Uses Magnus-Tetens approximation.
    """
    temp_c = (temp_f - 32.0) * 5.0 / 9.0
    rh = max(0.01, min(100.0, humidity_pct)) / 100.0
    a = 17.27
    b = 237.7
    alpha = (a * temp_c) / (b + temp_c) + math.log(rh)
    dp_c = (b * alpha) / (a - alpha)
    return dp_c * 9.0 / 5.0 + 32.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance between two lat/lon points in meters."""
    r = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


@dataclass
class GPXProfile:
    distance_meters: float
    elevation_gain_m: float
    elevation_loss_m: float
    avg_altitude_m: float
    max_altitude_m: float
    min_altitude_m: float
    segment_count: int


def parse_gpx(file_or_content: str | Path) -> GPXProfile:
    """Parse a GPX file and compute distance, elevation gain, loss, and altitude."""
    if isinstance(file_or_content, Path) or (
        isinstance(file_or_content, str) and "\n" not in file_or_content and Path(file_or_content).exists()
    ):
        tree = ET.parse(file_or_content)
        root = tree.getroot()
    else:
        root = ET.fromstring(file_or_content)

    # Handle XML namespaces
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    points: list[tuple[float, float, float]] = []  # lat, lon, ele

    for trkpt in root.iter(f"{ns}trkpt"):
        try:
            lat = float(trkpt.attrib["lat"])
            lon = float(trkpt.attrib["lon"])
            ele_elem = trkpt.find(f"{ns}ele")
            ele = float(ele_elem.text) if ele_elem is not None and ele_elem.text else 0.0
            points.append((lat, lon, ele))
        except (ValueError, KeyError):
            continue

    if not points:
        # Fallback to route points or waypoints
        for wpt in root.iter(f"{ns}wpt"):
            try:
                lat = float(wpt.attrib["lat"])
                lon = float(wpt.attrib["lon"])
                ele_elem = wpt.find(f"{ns}ele")
                ele = float(ele_elem.text) if ele_elem is not None and ele_elem.text else 0.0
                points.append((lat, lon, ele))
            except (ValueError, KeyError):
                continue

    if len(points) < 2:
        return GPXProfile(
            distance_meters=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            avg_altitude_m=0.0,
            max_altitude_m=0.0,
            min_altitude_m=0.0,
            segment_count=len(points),
        )

    total_dist = 0.0
    total_gain = 0.0
    total_loss = 0.0
    altitudes = [p[2] for p in points]

    for i in range(1, len(points)):
        p1, p2 = points[i - 1], points[i]
        d = haversine_distance(p1[0], p1[1], p2[0], p2[1])
        total_dist += d
        dh = p2[2] - p1[2]
        if dh > 0:
            total_gain += dh
        else:
            total_loss += abs(dh)

    return GPXProfile(
        distance_meters=round(total_dist, 1),
        elevation_gain_m=round(total_gain, 1),
        elevation_loss_m=round(total_loss, 1),
        avg_altitude_m=round(sum(altitudes) / len(altitudes), 1),
        max_altitude_m=round(max(altitudes), 1),
        min_altitude_m=round(min(altitudes), 1),
        segment_count=len(points),
    )


@dataclass
class EnvironmentalConditions:
    elevation_gain_m: float = 0.0
    elevation_loss_m: float = 0.0
    altitude_m: float = 0.0
    temp_f: float | None = None
    dew_point_f: float | None = None
    humidity_pct: float | None = None
    gpx_profile: GPXProfile | None = None


def extract_conditions(
    inputs: dict[str, Any], prefix: str = "", base_dir: Path | None = None
) -> EnvironmentalConditions:
    """Extract conditions from an input dict (supporting optional prefixes like 'target_').

    A relative GPX path is looked up in the working directory, then in `base_dir`
    (the model directory), so examples can use `data/sample_course.gpx`.
    """
    cond = EnvironmentalConditions()

    # GPX file
    gpx_key = f"{prefix}gpx_path" if prefix else "gpx_path"
    gpx_str = inputs.get(gpx_key)
    if gpx_str:
        gpx_src: str | Path = str(gpx_str)
        if "<" not in str(gpx_str):  # a path, not inline GPX XML
            gpx_path = Path(str(gpx_str))
            if not gpx_path.exists() and base_dir is not None and (base_dir / gpx_path).exists():
                gpx_path = base_dir / gpx_path
            if not gpx_path.exists():
                raise ValueError(f"{gpx_key}: GPX file not found: {gpx_str}")
            gpx_src = gpx_path
        try:
            profile = parse_gpx(gpx_src)
        except ET.ParseError as exc:
            raise ValueError(f"{gpx_key}: could not parse GPX ({exc})") from exc
        cond.gpx_profile = profile
        cond.elevation_gain_m = profile.elevation_gain_m
        cond.elevation_loss_m = profile.elevation_loss_m
        cond.altitude_m = profile.avg_altitude_m

    # Elevation gain/loss
    gain_key = f"{prefix}elevation_gain" if prefix else "elevation_gain"
    if inputs.get(gain_key) is not None:
        cond.elevation_gain_m = parse_elevation(inputs[gain_key])

    loss_key = f"{prefix}elevation_loss" if prefix else "elevation_loss"
    if inputs.get(loss_key) is not None:
        cond.elevation_loss_m = parse_elevation(inputs[loss_key])

    # Altitude
    alt_key = f"{prefix}altitude" if prefix else "altitude"
    if inputs.get(alt_key) is not None:
        cond.altitude_m = parse_elevation(inputs[alt_key])

    # Temperature & Humidity
    temp_key = f"{prefix}temp_f" if prefix else "temp_f"
    if inputs.get(temp_key) is not None:
        cond.temp_f = parse_temp(inputs[temp_key])

    dp_key = f"{prefix}dew_point_f" if prefix else "dew_point_f"
    if inputs.get(dp_key) is not None:
        cond.dew_point_f = parse_temp(inputs[dp_key])

    hum_key = f"{prefix}humidity_pct" if prefix else "humidity_pct"
    if inputs.get(hum_key) is not None:
        try:
            cond.humidity_pct = float(inputs[hum_key])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{hum_key} must be a number (percent), got {inputs[hum_key]!r}") from exc

    if cond.temp_f is not None and cond.humidity_pct is not None and cond.dew_point_f is None:
        cond.dew_point_f = dew_point_from_humidity(cond.temp_f, cond.humidity_pct)

    return cond


def compute_environmental_multipliers(
    distance_m: float,
    conditions: EnvironmentalConditions,
    params: Any,
) -> dict[str, Any]:
    """Compute adjustment multipliers for elevation, altitude, and weather.

    `params` is the model's resolved Params: every coefficient and the
    `elevation_multiplier`, `altitude_multiplier` and `weather_penalty_pct`
    formulas come from config.toml.
    """
    p = params
    d = max(distance_m, 1.0)

    # 1. Elevation grade factor (formula `elevation_multiplier`), floored for extreme downhills
    up_grade_pct = (conditions.elevation_gain_m / d) * 100.0
    down_grade_pct = (conditions.elevation_loss_m / d) * 100.0
    elevation_factor = p.formula(
        "elevation_multiplier", up_grade_pct=up_grade_pct, down_grade_pct=down_grade_pct
    )
    elevation_factor = max(p.min_elevation_multiplier, elevation_factor)

    # 2. Altitude factor (formula `altitude_multiplier`)
    excess_altitude_m = max(0.0, conditions.altitude_m - p.altitude_threshold_m)
    altitude_factor = p.formula("altitude_multiplier", altitude_m=conditions.altitude_m)

    # 3. Weather factor (formula `weather_penalty_pct`: heat/dew point strain and cold strain)
    weather_penalty_pct = 0.0
    if conditions.temp_f is not None:
        dp = (
            conditions.dew_point_f
            if conditions.dew_point_f is not None
            else conditions.temp_f * p.assumed_dew_point_ratio
        )
        weather_penalty_pct = p.formula(
            "weather_penalty_pct", temp_f=conditions.temp_f, dew_point_f=dp, distance_m=d
        )
    weather_factor = 1.0 + weather_penalty_pct / 100.0

    # Total combined multiplier: Course Time = Neutral Time * total_multiplier
    total_multiplier = elevation_factor * altitude_factor * weather_factor

    return {
        "elevation_factor": elevation_factor,
        "up_grade_pct": up_grade_pct,
        "down_grade_pct": down_grade_pct,
        "altitude_factor": altitude_factor,
        "excess_altitude_m": excess_altitude_m,
        "weather_factor": weather_factor,
        "weather_penalty_pct": weather_penalty_pct,
        "total_multiplier": total_multiplier,
    }


def normalize_to_neutral(
    observed_time_sec: float,
    distance_m: float,
    conditions: EnvironmentalConditions,
    params: Any,
) -> tuple[float, dict[str, Any]]:
    """Convert an observed time run on a hilly/hot course to its flat, sea-level neutral equivalent."""
    mults = compute_environmental_multipliers(distance_m, conditions, params)
    neutral_time = observed_time_sec / mults["total_multiplier"]
    return neutral_time, mults
