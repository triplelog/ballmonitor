"""Download and build historical race datasets for the race_podium model.

    ballmonitor fetch race_podium
    ballmonitor fetch race_podium --offline
"""

from __future__ import annotations

import csv
from pathlib import Path


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    data_dir = model_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sample_path = data_dir / "sample_results.csv"

    log = []
    # Build sample multi-year historical dataset if not present or refreshed
    rows = _generate_sample_results()
    with open(sample_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "name", "gender", "age", "time", "division_place"])
        writer.writeheader()
        writer.writerows(rows)

    log.append(f"wrote {len(rows)} runner results to {sample_path.name}")
    return log


def _generate_sample_results() -> list[dict[str, str]]:
    """Generate realistic multi-year road race results with persistent runners."""
    rows = []
    # 2021, 2022, 2023 editions
    years = [2021, 2022, 2023]

    # Pre-defined core contenders across years to test repeat runners and aging up
    runners = [
        # Male 40-44 contenders (plus runner aging in from 39)
        {"id": "M_A", "name": "Marcus Vance", "gender": "M", "birth_year": 1984, "base_time": 3215},  # 39 in 2023 -> 53:35
        {"id": "M_B", "name": "Brian Miller", "gender": "M", "birth_year": 1981, "base_time": 3280},  # 42 in 2023 -> 54:40
        {"id": "M_C", "name": "David Clark", "gender": "M", "birth_year": 1980, "base_time": 3340},
        {"id": "M_D", "name": "Eric Wright", "gender": "M", "birth_year": 1982, "base_time": 3390},
        {"id": "M_E", "name": "Kevin Ross", "gender": "M", "birth_year": 1979, "base_time": 3440},
        # Female 40-49 contenders (plus runner aging in from 39)
        {"id": "F_A", "name": "Sarah Jenkins", "gender": "F", "birth_year": 1984, "base_time": 3680},  # 39 in 2023
        {"id": "F_B", "name": "Lisa Adams", "gender": "F", "birth_year": 1981, "base_time": 3760},
        {"id": "F_C", "name": "Rachel Taylor", "gender": "F", "birth_year": 1978, "base_time": 3840},
        {"id": "F_D", "name": "Emily Scott", "gender": "F", "birth_year": 1975, "base_time": 3930},
        {"id": "F_E", "name": "Jessica White", "gender": "F", "birth_year": 1980, "base_time": 4010},
    ]

    weather_offsets = {2021: 20.0, 2022: -15.0, 2023: 0.0}

    for y in years:
        y_runners = []
        for r in runners:
            age = y - r["birth_year"]
            # Performance model: base time + aging degradation (0.75% per year above 30) + weather
            age_factor = 1.0 + (max(0, age - 30) * 0.0075)
            time_sec = round(r["base_time"] * age_factor + weather_offsets[y])
            h, rem = divmod(time_sec, 3600)
            m, s = divmod(rem, 60)
            t_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

            y_runners.append({
                "year": str(y),
                "name": r["name"],
                "gender": r["gender"],
                "age": str(age),
                "time": t_str,
            })

        for place, runner in enumerate(y_runners, 1):
            runner["division_place"] = str(place)
            rows.append(runner)

    return rows
