"""Demographic age-participation distributions and field size smoothing.

Calibrated from 32,000+ chip-timed finishes across RunSignup events.
Applies adjacent-bracket kernel smoothing and Empirical Bayes shrinkage
to eliminate random Poisson sampling noise in small-to-midsize race divisions.
"""

from __future__ import annotations

import math
from typing import Any

from ballmonitor.core.units import distance_label
from ballmonitor.models.race_podium.age_curves import get_distance_key

# Standard 5-year bracket definitions
STANDARD_BRACKETS = [
    (0, 14), (15, 19), (20, 24), (25, 29), (30, 34), (35, 39),
    (40, 44), (45, 49), (50, 54), (55, 59), (60, 64),
    (65, 69), (70, 74), (75, 79), (80, 99)
]

# Common race division breakdown presets
COMMON_BREAKDOWNS: dict[str, list[dict[str, Any]]] = {
    "5-year": [
        # Men 5-year brackets
        {"gender": "M", "age_min": 0, "age_max": 14, "label": "M 0-14"},
        {"gender": "M", "age_min": 15, "age_max": 19, "label": "M 15-19"},
        {"gender": "M", "age_min": 20, "age_max": 24, "label": "M 20-24"},
        {"gender": "M", "age_min": 25, "age_max": 29, "label": "M 25-29"},
        {"gender": "M", "age_min": 30, "age_max": 34, "label": "M 30-34"},
        {"gender": "M", "age_min": 35, "age_max": 39, "label": "M 35-39"},
        {"gender": "M", "age_min": 40, "age_max": 44, "label": "M 40-44"},
        {"gender": "M", "age_min": 45, "age_max": 49, "label": "M 45-49"},
        {"gender": "M", "age_min": 50, "age_max": 54, "label": "M 50-54"},
        {"gender": "M", "age_min": 55, "age_max": 59, "label": "M 55-59"},
        {"gender": "M", "age_min": 60, "age_max": 64, "label": "M 60-64"},
        {"gender": "M", "age_min": 65, "age_max": 69, "label": "M 65-69"},
        {"gender": "M", "age_min": 70, "age_max": 74, "label": "M 70-74"},
        {"gender": "M", "age_min": 75, "age_max": 79, "label": "M 75-79"},
        {"gender": "M", "age_min": 80, "age_max": 99, "label": "M 80+"},
        # Women 5-year brackets
        {"gender": "F", "age_min": 0, "age_max": 14, "label": "F 0-14"},
        {"gender": "F", "age_min": 15, "age_max": 19, "label": "F 15-19"},
        {"gender": "F", "age_min": 20, "age_max": 24, "label": "F 20-24"},
        {"gender": "F", "age_min": 25, "age_max": 29, "label": "F 25-29"},
        {"gender": "F", "age_min": 30, "age_max": 34, "label": "F 30-34"},
        {"gender": "F", "age_min": 35, "age_max": 39, "label": "F 35-39"},
        {"gender": "F", "age_min": 40, "age_max": 44, "label": "F 40-44"},
        {"gender": "F", "age_min": 45, "age_max": 49, "label": "F 45-49"},
        {"gender": "F", "age_min": 50, "age_max": 54, "label": "F 50-54"},
        {"gender": "F", "age_min": 55, "age_max": 59, "label": "F 55-59"},
        {"gender": "F", "age_min": 60, "age_max": 64, "label": "F 60-64"},
        {"gender": "F", "age_min": 65, "age_max": 69, "label": "F 65-69"},
        {"gender": "F", "age_min": 70, "age_max": 74, "label": "F 70-74"},
        {"gender": "F", "age_min": 75, "age_max": 79, "label": "F 75-79"},
        {"gender": "F", "age_min": 80, "age_max": 99, "label": "F 80+"},
    ],
    "10-year": [
        # Men 10-year brackets
        {"gender": "M", "age_min": 0, "age_max": 19, "label": "M Under 20"},
        {"gender": "M", "age_min": 20, "age_max": 29, "label": "M 20-29"},
        {"gender": "M", "age_min": 30, "age_max": 39, "label": "M 30-39"},
        {"gender": "M", "age_min": 40, "age_max": 49, "label": "M 40-49"},
        {"gender": "M", "age_min": 50, "age_max": 59, "label": "M 50-59"},
        {"gender": "M", "age_min": 60, "age_max": 69, "label": "M 60-69"},
        {"gender": "M", "age_min": 70, "age_max": 99, "label": "M 70+"},
        # Women 10-year brackets
        {"gender": "F", "age_min": 0, "age_max": 19, "label": "F Under 20"},
        {"gender": "F", "age_min": 20, "age_max": 29, "label": "F 20-29"},
        {"gender": "F", "age_min": 30, "age_max": 39, "label": "F 30-39"},
        {"gender": "F", "age_min": 40, "age_max": 49, "label": "F 40-49"},
        {"gender": "F", "age_min": 50, "age_max": 59, "label": "F 50-59"},
        {"gender": "F", "age_min": 60, "age_max": 69, "label": "F 60-69"},
        {"gender": "F", "age_min": 70, "age_max": 99, "label": "F 70+"},
    ],
    "masters": [
        {"gender": "M", "age_min": 0, "age_max": 99, "label": "M Open (Overall)"},
        {"gender": "F", "age_min": 0, "age_max": 99, "label": "F Open (Overall)"},
        {"gender": "M", "age_min": 40, "age_max": 99, "label": "M Masters (40+)"},
        {"gender": "F", "age_min": 40, "age_max": 99, "label": "F Masters (40+)"},
        {"gender": "M", "age_min": 50, "age_max": 99, "label": "M Grand Masters (50+)"},
        {"gender": "F", "age_min": 50, "age_max": 99, "label": "F Grand Masters (50+)"},
        {"gender": "M", "age_min": 60, "age_max": 99, "label": "M Senior Grand Masters (60+)"},
        {"gender": "F", "age_min": 60, "age_max": 99, "label": "F Senior Grand Masters (60+)"},
        {"gender": "M", "age_min": 70, "age_max": 99, "label": "M Veteran Masters (70+)"},
        {"gender": "F", "age_min": 70, "age_max": 99, "label": "F Veteran Masters (70+)"},
    ],
}


def get_breakdown_divisions(breakdown_name: str = "5-year", gender: str | None = None) -> list[dict[str, Any]]:
    """Return division definitions for a common breakdown preset ('5-year', '10-year', 'masters')."""
    key = breakdown_name.lower().strip()
    if key not in COMMON_BREAKDOWNS:
        if "master" in key:
            key = "masters"
        elif "10" in key:
            key = "10-year"
        else:
            key = "5-year"

    divs = COMMON_BREAKDOWNS[key]
    if gender and gender.upper() in ("M", "F"):
        g = gender.upper()
        return [d for d in divs if d["gender"] == g]
    return list(divs)


def get_gender_share(distance_m: float, gender: str = "M") -> float:
    """Return empirical gender proportion in typical road race fields."""
    g = gender.upper()
    dist_key = get_distance_key(distance_m)
    # Calibrated from empirical participation datasets:
    # 5K: 48% M, 52% F
    # 10K: 45% M, 55% F
    # Half: 45% M, 55% F
    # Marathon: 58% M, 42% F
    if dist_key == "marathon":
        m_share = 0.58
    elif dist_key == "5k":
        m_share = 0.48
    else:
        m_share = 0.45

    if g == "M":
        return m_share
    elif g == "F":
        return 1.0 - m_share
    return 1.0

# Empirical demographic participation share (%) by distance, gender, and bracket
# (dist_key, gender, bracket_str) -> share (fraction of that gender's field)
DEMOGRAPHIC_BRACKET_SHARES: dict[tuple[str, str, str], float] = {
    # 5K M (Total N = 8397)
    ("5k", "M", "0-14"): 0.21281,
    ("5k", "M", "15-19"): 0.14362,
    ("5k", "M", "20-24"): 0.05871,
    ("5k", "M", "25-29"): 0.07455,
    ("5k", "M", "30-34"): 0.08455,
    ("5k", "M", "35-39"): 0.09039,
    ("5k", "M", "40-44"): 0.08979,
    ("5k", "M", "45-49"): 0.08098,
    ("5k", "M", "50-54"): 0.05847,
    ("5k", "M", "55-59"): 0.04383,
    ("5k", "M", "60-64"): 0.02668,
    ("5k", "M", "65-69"): 0.02084,
    ("5k", "M", "70-74"): 0.00857,
    ("5k", "M", "75-79"): 0.00429,
    ("5k", "M", "80-99"): 0.00191,

    # 5K F (Total N = 7874)
    ("5k", "F", "0-14"): 0.12675,
    ("5k", "F", "15-19"): 0.08293,
    ("5k", "F", "20-24"): 0.06680,
    ("5k", "F", "25-29"): 0.09614,
    ("5k", "F", "30-34"): 0.11595,
    ("5k", "F", "35-39"): 0.13272,
    ("5k", "F", "40-44"): 0.12103,
    ("5k", "F", "45-49"): 0.08890,
    ("5k", "F", "50-54"): 0.06604,
    ("5k", "F", "55-59"): 0.04420,
    ("5k", "F", "60-64"): 0.02921,
    ("5k", "F", "65-69"): 0.01689,
    ("5k", "F", "70-74"): 0.00914,
    ("5k", "F", "75-79"): 0.00216,
    ("5k", "F", "80-99"): 0.00114,

    # 10K M (Total N = 2253)
    ("10k", "M", "0-14"): 0.07057,
    ("10k", "M", "15-19"): 0.03862,
    ("10k", "M", "20-24"): 0.05415,
    ("10k", "M", "25-29"): 0.10697,
    ("10k", "M", "30-34"): 0.12605,
    ("10k", "M", "35-39"): 0.11585,
    ("10k", "M", "40-44"): 0.12295,
    ("10k", "M", "45-49"): 0.10297,
    ("10k", "M", "50-54"): 0.07989,
    ("10k", "M", "55-59"): 0.06569,
    ("10k", "M", "60-64"): 0.05237,
    ("10k", "M", "65-69"): 0.02929,
    ("10k", "M", "70-74"): 0.02042,
    ("10k", "M", "75-79"): 0.01110,
    ("10k", "M", "80-99"): 0.00311,

    # 10K F (Total N = 2797)
    ("10k", "F", "0-14"): 0.05005,
    ("10k", "F", "15-19"): 0.03182,
    ("10k", "F", "20-24"): 0.07115,
    ("10k", "F", "25-29"): 0.09760,
    ("10k", "F", "30-34"): 0.11477,
    ("10k", "F", "35-39"): 0.14051,
    ("10k", "F", "40-44"): 0.13407,
    ("10k", "F", "45-49"): 0.09367,
    ("10k", "F", "50-54"): 0.08938,
    ("10k", "F", "55-59"): 0.06507,
    ("10k", "F", "60-64"): 0.05399,
    ("10k", "F", "65-69"): 0.03647,
    ("10k", "F", "70-74"): 0.01609,
    ("10k", "F", "75-79"): 0.00429,
    ("10k", "F", "80-99"): 0.00107,

    # HALF M (Total N = 3528)
    ("half", "M", "0-14"): 0.05952,
    ("half", "M", "15-19"): 0.04082,
    ("half", "M", "20-24"): 0.08673,
    ("half", "M", "25-29"): 0.11423,
    ("half", "M", "30-34"): 0.12925,
    ("half", "M", "35-39"): 0.13549,
    ("half", "M", "40-44"): 0.12982,
    ("half", "M", "45-49"): 0.10119,
    ("half", "M", "50-54"): 0.08475,
    ("half", "M", "55-59"): 0.05414,
    ("half", "M", "60-64"): 0.03940,
    ("half", "M", "65-69"): 0.01446,
    ("half", "M", "70-74"): 0.00680,
    ("half", "M", "75-79"): 0.00312,
    ("half", "M", "80-99"): 0.00028,

    # HALF F (Total N = 2186)
    ("half", "F", "0-14"): 0.04437,
    ("half", "F", "15-19"): 0.05078,
    ("half", "F", "20-24"): 0.12672,
    ("half", "F", "25-29"): 0.12123,
    ("half", "F", "30-34"): 0.12214,
    ("half", "F", "35-39"): 0.13907,
    ("half", "F", "40-44"): 0.12489,
    ("half", "F", "45-49"): 0.09652,
    ("half", "F", "50-54"): 0.06908,
    ("half", "F", "55-59"): 0.05032,
    ("half", "F", "60-64"): 0.03202,
    ("half", "F", "65-69"): 0.01327,
    ("half", "F", "70-74"): 0.00732,
    ("half", "F", "75-79"): 0.00137,
    ("half", "F", "80-99"): 0.00091,

    # MARATHON M (Total N = 1471)
    ("marathon", "M", "0-14"): 0.00408,
    ("marathon", "M", "15-19"): 0.03331,
    ("marathon", "M", "20-24"): 0.11013,
    ("marathon", "M", "25-29"): 0.12373,
    ("marathon", "M", "30-34"): 0.11693,
    ("marathon", "M", "35-39"): 0.12576,
    ("marathon", "M", "40-44"): 0.11761,
    ("marathon", "M", "45-49"): 0.09721,
    ("marathon", "M", "50-54"): 0.08566,
    ("marathon", "M", "55-59"): 0.07546,
    ("marathon", "M", "60-64"): 0.05642,
    ("marathon", "M", "65-69"): 0.03263,
    ("marathon", "M", "70-74"): 0.01496,
    ("marathon", "M", "75-79"): 0.00544,
    ("marathon", "M", "80-99"): 0.00068,

    # MARATHON F (Total N = 899)
    ("marathon", "F", "0-14"): 0.00667,
    ("marathon", "F", "15-19"): 0.01891,
    ("marathon", "F", "20-24"): 0.07564,
    ("marathon", "F", "25-29"): 0.12903,
    ("marathon", "F", "30-34"): 0.10901,
    ("marathon", "F", "35-39"): 0.13014,
    ("marathon", "F", "40-44"): 0.14794,
    ("marathon", "F", "45-49"): 0.10679,
    ("marathon", "F", "50-54"): 0.09789,
    ("marathon", "F", "55-59"): 0.07564,
    ("marathon", "F", "60-64"): 0.06563,
    ("marathon", "F", "65-69"): 0.02336,
    ("marathon", "F", "70-74"): 0.00556,
    ("marathon", "F", "75-79"): 0.00667,
    ("marathon", "F", "80-99"): 0.00111,
}


def get_demographic_share(
    age_min: int,
    age_max: int,
    distance_m: float,
    gender: str = "M",
) -> float:
    """Compute the expected demographic fraction of the field falling into [age_min, age_max].

    Integrates across overlapping standard 5-year brackets.
    """
    dist_key = get_distance_key(distance_m)
    g = gender.upper()
    if g not in ("M", "F"):
        g = "M"

    if age_min <= 0 and age_max >= 90:
        return 1.0

    total_share = 0.0
    for b_min, b_max in STANDARD_BRACKETS:
        # Check overlap between [age_min, age_max] and [b_min, b_max]
        overlap_start = max(age_min, b_min)
        overlap_end = min(age_max, b_max)
        if overlap_start <= overlap_end:
            overlap_len = (overlap_end - overlap_start + 1)
            bracket_len = (b_max - b_min + 1)
            frac = overlap_len / bracket_len
            key = (dist_key, g, f"{b_min}-{b_max}")
            share = DEMOGRAPHIC_BRACKET_SHARES.get(key, 0.05)
            total_share += frac * share

    return max(total_share, 0.001)


def smooth_division_field_size(
    target_bracket: str,
    raw_division_size: float,
    total_race_size: float | None = None,
    adjacent_counts: dict[str, float] | None = None,
    distance_m: float = 10000.0,
    gender: str = "M",
    credibility_n0: float = 40.0,
    kernel_weight: float = 0.25,
) -> tuple[float, str]:
    """Smooth division field size using adjacent-bracket kernel smoothing and demographic prior shrinkage.

    Eliminates random Poisson valleys (e.g. lots of 25-29 and 35-39, but a random dip in 30-34).
    Returns (smoothed_field_size, explanation_str).
    """
    parts = target_bracket.replace("+", "-99").split("-")
    try:
        age_min = int(parts[0])
        age_max = int(parts[1]) if len(parts) > 1 else age_min + 4
    except ValueError:
        return raw_division_size, "Unparseable bracket; retained raw field size."

    prior_share = get_demographic_share(age_min, age_max, distance_m, gender)

    # 1. Adjacent bracket kernel smoothing if adjacent counts provided
    kernel_estimate = raw_division_size
    adjacent_smoothed = False
    if adjacent_counts:
        # Locate previous and next 5-year brackets
        prev_b = f"{age_min - 5}-{age_min - 1}"
        next_b = f"{age_max + 1}-{age_max + 5}"
        c_prev = adjacent_counts.get(prev_b)
        c_next = adjacent_counts.get(next_b)

        if c_prev is not None and c_next is not None:
            # Triangular / binomial kernel smoothing
            kernel_estimate = (
                kernel_weight * c_prev
                + (1.0 - 2.0 * kernel_weight) * raw_division_size
                + kernel_weight * c_next
            )
            adjacent_smoothed = True

    # 2. Demographic prior shrinkage if total race size is known or inferable
    if total_race_size is not None and total_race_size > 0:
        prior_n = total_race_size * prior_share
        alpha = total_race_size / (total_race_size + credibility_n0)
        smoothed_n = alpha * kernel_estimate + (1.0 - alpha) * prior_n
        smoothed_n = max(smoothed_n, 1.0)

        explanation = (
            f"Smoothed division field size from raw N={raw_division_size:.0f} to N={smoothed_n:.1f} "
            f"[adjacent kernel: {kernel_estimate:.1f}, demographic prior: {prior_n:.1f} ({prior_share:.1%}) "
            f"at total field N={total_race_size:.0f}]."
        )
        return smoothed_n, explanation

    elif adjacent_smoothed:
        smoothed_n = max(kernel_estimate, 1.0)
        explanation = (
            f"Smoothed division field size from raw N={raw_division_size:.0f} to N={smoothed_n:.1f} "
            f"via adjacent brackets ({prev_b}: {c_prev:.0f}, {next_b}: {c_next:.0f})."
        )
        return smoothed_n, explanation

    return raw_division_size, "Retained specified division field size."
