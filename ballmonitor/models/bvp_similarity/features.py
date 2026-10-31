"""Feature extraction and similarity engine for Batter vs. Pitcher (BvP) matchups.

Extracts rich physical, repertoire, plate discipline, and outcome features from
Statcast pitch-by-pitch data, computes multidimensional similarity metrics across
pitchers and batters, and pools cross-archetype matchup samples to solve the small
sample size problem in BvP modeling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

# Pitch family groupings
FASTBALLS = {"FF", "SI", "FC"}
BREAKING = {"SL", "ST", "SV", "CU", "KC"}
OFFSPEED = {"CH", "FS", "FO", "KN", "SC"}

# League average defaults for imputation when sample size is zero
LEAGUE_DEFAULTS = {
    "velo_fb": 93.8,
    "velo_br": 83.8,
    "velo_os": 86.2,
    "velo_diff": 7.6,
    "zone_pct": 0.485,
    "chase_pct": 0.295,
    "z_swing_pct": 0.675,
    "whiff_pct": 0.245,
    "csw_pct": 0.275,
    "k_pct": 0.225,
    "bb_pct": 0.082,
    "hard_hit_pct": 0.385,
    "gb_pct": 0.425,
    "fb_pct": 0.355,
    "xwoba": 0.315,
    "woba": 0.315,
    "f_strike_pct": 0.525,
    "f_zone_pct": 0.490,
    "ahead_zone_pct": 0.340,
    "ahead_whiff_pct": 0.310,
    "behind_fb_pct": 0.750,
    "behind_zone_pct": 0.580,
    "f_swing_pct": 0.285,
    "chase_2s_pct": 0.420,
    "whiff_2s_pct": 0.220,
}

PITCHER_SIM_COLS = [
    "pct_ff", "pct_si", "pct_fc", "pct_sl", "pct_st", "pct_cu", "pct_ch", "pct_fs",
    "velo_fb", "velo_br", "velo_diff",
    "zone_pct", "chase_pct", "whiff_pct", "csw_pct",
    "k_pct", "bb_pct", "hard_hit_pct", "xwoba",
    "f_strike_pct", "f_zone_pct", "ahead_zone_pct", "behind_fb_pct",
]

BATTER_SIM_COLS = [
    "k_pct", "bb_pct", "chase_pct", "z_contact_pct", "whiff_pct",
    "whiff_fb", "whiff_br", "whiff_os", "whiff_hi",
    "hard_hit_pct", "gb_pct", "fb_pct", "xwoba",
    "f_swing_pct", "chase_2s_pct", "whiff_2s_pct",
]


def find_pitches_dir(model_dir: Path | None = None) -> Path:
    """Locate the directory containing Statcast pitch parquet files."""
    candidates = []
    if model_dir:
        candidates.append(model_dir / "data" / "pitches")
        candidates.append(model_dir.parent / "next_pitch" / "data" / "pitches")
    candidates.append(Path(__file__).resolve().parent / "data" / "pitches")
    candidates.append(Path(__file__).resolve().parent.parent / "next_pitch" / "data" / "pitches")

    for c in candidates:
        if c.exists() and any(c.glob("*.parquet")):
            return c
    raise FileNotFoundError("Could not find Statcast pitch parquet files in next_pitch/data/pitches or local data/pitches.")


def load_people(model_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load player identity metadata (names, bats, throws) from people.json."""
    candidates = []
    if model_dir:
        candidates.append(model_dir / "data" / "raw" / "people.json")
        candidates.append(model_dir.parent / "next_pitch" / "data" / "raw" / "people.json")
    candidates.append(Path(__file__).resolve().parent / "data" / "raw" / "people.json")
    candidates.append(Path(__file__).resolve().parent.parent / "next_pitch" / "data" / "raw" / "people.json")

    for c in candidates:
        if c.exists():
            with open(c) as f:
                return json.load(f)
    return {}


def load_pitches(
    pitches_dir: Path,
    seasons: list[int] | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Read pitch parquet files for specified seasons with optional point-in-time cutoff."""
    all_files = sorted(pitches_dir.glob("*.parquet"))
    if seasons is not None:
        season_strs = {str(s) for s in seasons}
        files = [f for f in all_files if f.stem in season_strs]
    else:
        files = all_files

    if not files:
        raise FileNotFoundError(f"No parquet files matching seasons {seasons} in {pitches_dir}")

    cols = [
        "game_pk", "game_date", "pitcher", "player_name", "batter", "stand", "p_throws",
        "balls", "strikes", "pt", "release_speed", "plate_x", "plate_z", "swing", "whiff", "csw", "in_zone", "events",
        "woba_value", "woba_denom", "estimated_woba_using_speedangle", "delta_run_exp",
        "launch_speed", "launch_angle", "bb_type"
    ]
    frames = [pd.read_parquet(f, columns=cols) for f in files]
    df = pd.concat(frames, ignore_index=True)

    if as_of_date:
        df = df[df["game_date"] <= as_of_date].copy()

    return add_pitch_indicators(df)


def add_pitch_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add vectorized boolean indicator columns for fast downstream aggregations."""
    df = df.copy()

    # Pitch family flags
    df["is_fb"] = df["pt"].isin(FASTBALLS)
    df["is_br"] = df["pt"].isin(BREAKING)
    df["is_os"] = df["pt"].isin(OFFSPEED)
    df["is_hi"] = df["release_speed"] >= 95.0

    # Zone and swing flags
    df["out_zone"] = (df["in_zone"] == 0).astype(np.int8)
    df["chase_swing"] = ((df["swing"] == 1) & (df["out_zone"] == 1)).astype(np.int8)
    df["zone_swing"] = ((df["swing"] == 1) & (df["in_zone"] == 1)).astype(np.int8)
    df["zone_contact"] = ((df["zone_swing"] == 1) & (df["whiff"] == 0)).astype(np.int8)

    # Swings and whiffs by pitch family
    df["swing_fb"] = ((df["swing"] == 1) & df["is_fb"]).astype(np.int8)
    df["whiff_fb"] = ((df["whiff"] == 1) & df["is_fb"]).astype(np.int8)
    df["swing_br"] = ((df["swing"] == 1) & df["is_br"]).astype(np.int8)
    df["whiff_br"] = ((df["whiff"] == 1) & df["is_br"]).astype(np.int8)
    df["swing_os"] = ((df["swing"] == 1) & df["is_os"]).astype(np.int8)
    df["whiff_os"] = ((df["whiff"] == 1) & df["is_os"]).astype(np.int8)
    df["swing_hi"] = ((df["swing"] == 1) & df["is_hi"]).astype(np.int8)
    df["whiff_hi"] = ((df["whiff"] == 1) & df["is_hi"]).astype(np.int8)

    # Plate appearance and outcome flags
    df["is_pa"] = (df["woba_denom"] == 1).astype(np.int8)
    events_str = df["events"].fillna("")
    df["is_k"] = events_str.str.startswith("strikeout").astype(np.int8)
    df["is_bb"] = events_str.isin({"walk", "intent_walk"}).astype(np.int8)
    df["is_hbp"] = (events_str == "hit_by_pitch").astype(np.int8)
    df["is_h"] = events_str.isin({"single", "double", "triple", "home_run"}).astype(np.int8)
    df["is_hr"] = (events_str == "home_run").astype(np.int8)
    df["is_single"] = (events_str == "single").astype(np.int8)
    df["is_double"] = (events_str == "double").astype(np.int8)
    df["is_triple"] = (events_str == "triple").astype(np.int8)

    # Batted ball quality
    # Statcast also records launch speed on many fouls, so a ball in play needs a PA-ending event
    # and a batted-ball type (data built before v0.2.1 counted fouls here; see MODEL.md changelog)
    df["is_bip"] = (df["events"].notna() & df["bb_type"].notna() & df["launch_speed"].notna()).astype(np.int8)
    df["hard_hit"] = ((df["launch_speed"] >= 95.0) & (df["is_bip"] == 1)).astype(np.int8)
    df["is_gb"] = (df["bb_type"] == "ground_ball").astype(np.int8)
    df["is_fb_bip"] = (df["bb_type"] == "fly_ball").astype(np.int8)

    # Standard xwOBA definition: combine_first woba_value for walks/Ks/HBPs
    df["xwoba_val"] = df["estimated_woba_using_speedangle"].combine_first(df["woba_value"])

    # Count state indicators
    df["is_00"] = ((df["balls"] == 0) & (df["strikes"] == 0)).astype(np.int8)
    df["is_2s"] = (df["strikes"] == 2).astype(np.int8)
    df["is_behind"] = ((df["balls"] >= 2) & (df["strikes"] <= 1)).astype(np.int8)

    is_strike_00 = (df["swing"] == 1) | (df["csw"] == 1)
    df["strike_00"] = (df["is_00"] & is_strike_00).astype(np.int8)
    df["zone_00"] = (df["is_00"] & (df["in_zone"] == 1)).astype(np.int8)
    df["swing_00"] = (df["is_00"] & (df["swing"] == 1)).astype(np.int8)

    df["zone_2s"] = (df["is_2s"] & (df["in_zone"] == 1)).astype(np.int8)
    df["out_zone_2s"] = (df["is_2s"] & (df["out_zone"] == 1)).astype(np.int8)
    df["chase_2s"] = (df["is_2s"] & (df["chase_swing"] == 1)).astype(np.int8)
    df["whiff_2s"] = (df["is_2s"] & (df["whiff"] == 1)).astype(np.int8)
    df["swing_2s"] = (df["is_2s"] & (df["swing"] == 1)).astype(np.int8)

    df["fb_behind"] = (df["is_behind"] & df["is_fb"]).astype(np.int8)
    df["zone_behind"] = (df["is_behind"] & (df["in_zone"] == 1)).astype(np.int8)
    df["swing_behind"] = (df["is_behind"] & (df["swing"] == 1)).astype(np.int8)

    return df


def extract_pitcher_features(
    df: pd.DataFrame,
    people: dict[str, dict[str, Any]] | None = None,
    min_pitches: int = 150,
) -> pd.DataFrame:
    """Aggregate pitch-level data into comprehensive pitcher feature profiles."""
    if people is None:
        people = {}

    # 1. Base counts
    base = df.groupby("pitcher").agg(
        pitches=("pt", "count"),
        throws=("p_throws", "last"),
        name_raw=("player_name", "last"),
        pa=("is_pa", "sum"),
        k=("is_k", "sum"),
        bb=("is_bb", "sum"),
        h=("is_h", "sum"),
        hr=("is_hr", "sum"),
        swings=("swing", "sum"),
        whiffs=("whiff", "sum"),
        csw=("csw", "sum"),
        in_zone=("in_zone", "sum"),
        out_zone=("out_zone", "sum"),
        chase_swings=("chase_swing", "sum"),
        bip=("is_bip", "sum"),
        hard_hits=("hard_hit", "sum"),
        gb=("is_gb", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
        woba_sum=("woba_value", "sum"),
        delta_re=("delta_run_exp", "sum"),
        pitches_00=("is_00", "sum"),
        strikes_00=("strike_00", "sum"),
        zone_00=("zone_00", "sum"),
        pitches_2s=("is_2s", "sum"),
        zone_2s=("zone_2s", "sum"),
        swings_2s=("swing_2s", "sum"),
        whiffs_2s=("whiff_2s", "sum"),
        pitches_behind=("is_behind", "sum"),
        fb_behind=("fb_behind", "sum"),
        zone_behind=("zone_behind", "sum"),
    )

    base = base[base["pitches"] >= min_pitches].copy()
    valid_pitchers = set(base.index)
    df_p = df[df["pitcher"].isin(valid_pitchers)]

    # 2. Repertoire mix %
    pt_counts = df_p.groupby(["pitcher", "pt"]).size().unstack(fill_value=0)
    pt_mix = pt_counts.div(pt_counts.sum(axis=1), axis=0)
    for p in ["FF", "SI", "FC", "SL", "ST", "CU", "KC", "CH", "FS"]:
        if p not in pt_mix.columns:
            pt_mix[p] = 0.0

    base["pct_ff"] = pt_mix["FF"]
    base["pct_si"] = pt_mix["SI"]
    base["pct_fc"] = pt_mix["FC"]
    base["pct_sl"] = pt_mix["SL"]
    base["pct_st"] = pt_mix["ST"]
    base["pct_cu"] = pt_mix["CU"] + pt_mix["KC"]
    base["pct_ch"] = pt_mix["CH"]
    base["pct_fs"] = pt_mix["FS"]

    # 3. Velocities by pitch family
    velo_fb = df_p[df_p["is_fb"]].groupby("pitcher")["release_speed"].mean()
    velo_br = df_p[df_p["is_br"]].groupby("pitcher")["release_speed"].mean()
    velo_os = df_p[df_p["is_os"]].groupby("pitcher")["release_speed"].mean()

    base["velo_fb"] = base.index.map(velo_fb).fillna(LEAGUE_DEFAULTS["velo_fb"])
    base["velo_br"] = base.index.map(velo_br).fillna(LEAGUE_DEFAULTS["velo_br"])
    base["velo_os"] = base.index.map(velo_os).fillna(LEAGUE_DEFAULTS["velo_os"])
    base["velo_diff"] = base["velo_fb"] - base["velo_os"]

    # 4. Command & Quality of contact
    base["zone_pct"] = base["in_zone"] / base["pitches"]
    base["chase_pct"] = base["chase_swings"] / base["out_zone"].replace(0, np.nan)
    base["chase_pct"] = base["chase_pct"].fillna(LEAGUE_DEFAULTS["chase_pct"])
    base["whiff_pct"] = base["whiffs"] / base["swings"].replace(0, np.nan)
    base["whiff_pct"] = base["whiff_pct"].fillna(LEAGUE_DEFAULTS["whiff_pct"])
    base["csw_pct"] = base["csw"] / base["pitches"]
    base["k_pct"] = base["k"] / base["pa"].replace(0, np.nan)
    base["k_pct"] = base["k_pct"].fillna(LEAGUE_DEFAULTS["k_pct"])
    base["bb_pct"] = base["bb"] / base["pa"].replace(0, np.nan)
    base["bb_pct"] = base["bb_pct"].fillna(LEAGUE_DEFAULTS["bb_pct"])
    base["hard_hit_pct"] = base["hard_hits"] / base["bip"].replace(0, np.nan)
    base["hard_hit_pct"] = base["hard_hit_pct"].fillna(LEAGUE_DEFAULTS["hard_hit_pct"])
    base["gb_pct"] = base["gb"] / base["bip"].replace(0, np.nan)
    base["gb_pct"] = base["gb_pct"].fillna(LEAGUE_DEFAULTS["gb_pct"])

    base["xwoba"] = base["xwoba_sum"] / base["pa"].replace(0, np.nan)
    base["xwoba"] = base["xwoba"].fillna(LEAGUE_DEFAULTS["xwoba"])
    base["woba"] = base["woba_sum"] / base["pa"].replace(0, np.nan)
    base["woba"] = base["woba"].fillna(LEAGUE_DEFAULTS["woba"])

    # Count tendencies
    base["f_strike_pct"] = (base["strikes_00"] / base["pitches_00"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["f_strike_pct"])
    base["f_zone_pct"] = (base["zone_00"] / base["pitches_00"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["f_zone_pct"])
    base["ahead_zone_pct"] = (base["zone_2s"] / base["pitches_2s"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["ahead_zone_pct"])
    base["ahead_whiff_pct"] = (base["whiffs_2s"] / base["swings_2s"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["ahead_whiff_pct"])
    base["behind_fb_pct"] = (base["fb_behind"] / base["pitches_behind"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["behind_fb_pct"])
    base["behind_zone_pct"] = (base["zone_behind"] / base["pitches_behind"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["behind_zone_pct"])

    # 5. Platoon splits
    pa_p = df_p[df_p["is_pa"] == 1]
    platoon = pa_p.groupby(["pitcher", "stand"]).agg(
        pa=("events", "count"),
        k=("is_k", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
    ).unstack(fill_value=0)

    for side in ["L", "R"]:
        if ("pa", side) not in platoon.columns:
            platoon[("pa", side)] = 0
            platoon[("k", side)] = 0
            platoon[("xwoba_sum", side)] = 0.0

    pa_L = platoon[("pa", "L")].reindex(base.index, fill_value=0)
    k_L = platoon[("k", "L")].reindex(base.index, fill_value=0)
    xwoba_L = platoon[("xwoba_sum", "L")].reindex(base.index, fill_value=0.0)

    pa_R = platoon[("pa", "R")].reindex(base.index, fill_value=0)
    k_R = platoon[("k", "R")].reindex(base.index, fill_value=0)
    xwoba_R = platoon[("xwoba_sum", "R")].reindex(base.index, fill_value=0.0)

    base["pa_vs_L"] = pa_L
    base["k_pct_vs_L"] = (k_L / pa_L.replace(0, np.nan)).fillna(base["k_pct"])
    base["xwoba_vs_L"] = (xwoba_L / pa_L.replace(0, np.nan)).fillna(base["xwoba"])

    base["pa_vs_R"] = pa_R
    base["k_pct_vs_R"] = (k_R / pa_R.replace(0, np.nan)).fillna(base["k_pct"])
    base["xwoba_vs_R"] = (xwoba_R / pa_R.replace(0, np.nan)).fillna(base["xwoba"])

    # Clean name
    names = []
    for pid in base.index:
        p_info = people.get(str(pid))
        if p_info and p_info.get("name"):
            names.append(p_info["name"])
        else:
            raw = base.loc[pid, "name_raw"]
            if isinstance(raw, str) and "," in raw:
                parts = [p.strip() for p in raw.split(",")]
                names.append(f"{parts[1]} {parts[0]}")
            else:
                names.append(str(raw) if pd.notna(raw) else str(pid))
    base["name"] = names
    base.drop(columns=["name_raw"], inplace=True)

    return base.sort_values("pitches", ascending=False)


def extract_batter_features(
    df: pd.DataFrame,
    people: dict[str, dict[str, Any]] | None = None,
    min_pa: int = 50,
) -> pd.DataFrame:
    """Aggregate pitch-level data into comprehensive batter feature profiles."""
    if people is None:
        people = {}

    base = df.groupby("batter").agg(
        pitches=("pt", "count"),
        pa=("is_pa", "sum"),
        k=("is_k", "sum"),
        bb=("is_bb", "sum"),
        h=("is_h", "sum"),
        hr=("is_hr", "sum"),
        swings=("swing", "sum"),
        whiffs=("whiff", "sum"),
        chase_swings=("chase_swing", "sum"),
        out_zone=("out_zone", "sum"),
        in_zones=("in_zone", "sum"),
        zone_swings=("zone_swing", "sum"),
        zone_contacts=("zone_contact", "sum"),
        swing_fb=("swing_fb", "sum"),
        whiff_fb=("whiff_fb", "sum"),
        swing_br=("swing_br", "sum"),
        whiff_br=("whiff_br", "sum"),
        swing_os=("swing_os", "sum"),
        whiff_os=("whiff_os", "sum"),
        swing_hi=("swing_hi", "sum"),
        whiff_hi=("whiff_hi", "sum"),
        bip=("is_bip", "sum"),
        hard_hits=("hard_hit", "sum"),
        gb=("is_gb", "sum"),
        fb_bip=("is_fb_bip", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
        woba_sum=("woba_value", "sum"),
        delta_re=("delta_run_exp", "sum"),
        pitches_00=("is_00", "sum"),
        swings_00=("swing_00", "sum"),
        pitches_2s=("is_2s", "sum"),
        out_zones_2s=("out_zone_2s", "sum"),
        chases_2s=("chase_2s", "sum"),
        swings_2s=("swing_2s", "sum"),
        whiffs_2s=("whiff_2s", "sum"),
        pitches_behind=("is_behind", "sum"),
        swings_behind=("swing_behind", "sum"),
    )

    base = base[base["pa"] >= min_pa].copy()
    valid_batters = set(base.index)
    df_b = df[df["batter"].isin(valid_batters)]

    # Plate discipline
    base["k_pct"] = (base["k"] / base["pa"]).fillna(LEAGUE_DEFAULTS["k_pct"])
    base["bb_pct"] = (base["bb"] / base["pa"]).fillna(LEAGUE_DEFAULTS["bb_pct"])
    base["chase_pct"] = (base["chase_swings"] / base["out_zone"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["chase_pct"])
    base["z_swing_pct"] = (base["zone_swings"] / base["in_zones"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["z_swing_pct"])
    base["z_contact_pct"] = (base["zone_contacts"] / base["zone_swings"].replace(0, np.nan)).fillna(0.82)
    base["whiff_pct"] = (base["whiffs"] / base["swings"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["whiff_pct"])

    # Whiffs by pitch family
    base["whiff_fb"] = (base["whiff_fb"] / base["swing_fb"].replace(0, np.nan)).fillna(base["whiff_pct"])
    base["whiff_br"] = (base["whiff_br"] / base["swing_br"].replace(0, np.nan)).fillna(base["whiff_pct"])
    base["whiff_os"] = (base["whiff_os"] / base["swing_os"].replace(0, np.nan)).fillna(base["whiff_pct"])
    base["whiff_hi"] = (base["whiff_hi"] / base["swing_hi"].replace(0, np.nan)).fillna(base["whiff_fb"])

    # Batted ball quality
    base["hard_hit_pct"] = (base["hard_hits"] / base["bip"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["hard_hit_pct"])
    base["gb_pct"] = (base["gb"] / base["bip"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["gb_pct"])
    base["fb_pct"] = (base["fb_bip"] / base["bip"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["fb_pct"])
    base["xwoba"] = (base["xwoba_sum"] / base["pa"]).fillna(LEAGUE_DEFAULTS["xwoba"])
    base["woba"] = (base["woba_sum"] / base["pa"]).fillna(LEAGUE_DEFAULTS["woba"])

    # Count tendencies
    base["f_swing_pct"] = (base["swings_00"] / base["pitches_00"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["f_swing_pct"])
    base["chase_2s_pct"] = (base["chases_2s"] / base["out_zones_2s"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["chase_2s_pct"])
    base["whiff_2s_pct"] = (base["whiffs_2s"] / base["swings_2s"].replace(0, np.nan)).fillna(LEAGUE_DEFAULTS["whiff_2s_pct"])
    base["behind_swing_pct"] = (base["swings_behind"] / base["pitches_behind"].replace(0, np.nan)).fillna(0.65)

    # Platoon splits
    pa_b = df_b[df_b["is_pa"] == 1]
    platoon = pa_b.groupby(["batter", "p_throws"]).agg(
        pa=("events", "count"),
        k=("is_k", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
    ).unstack(fill_value=0)

    for side in ["L", "R"]:
        if ("pa", side) not in platoon.columns:
            platoon[("pa", side)] = 0
            platoon[("k", side)] = 0
            platoon[("xwoba_sum", side)] = 0.0

    pa_L = platoon[("pa", "L")].reindex(base.index, fill_value=0)
    k_L = platoon[("k", "L")].reindex(base.index, fill_value=0)
    xwoba_L = platoon[("xwoba_sum", "L")].reindex(base.index, fill_value=0.0)

    pa_R = platoon[("pa", "R")].reindex(base.index, fill_value=0)
    k_R = platoon[("k", "R")].reindex(base.index, fill_value=0)
    xwoba_R = platoon[("xwoba_sum", "R")].reindex(base.index, fill_value=0.0)

    base["pa_vs_L"] = pa_L
    base["k_pct_vs_L"] = (k_L / pa_L.replace(0, np.nan)).fillna(base["k_pct"])
    base["xwoba_vs_L"] = (xwoba_L / pa_L.replace(0, np.nan)).fillna(base["xwoba"])

    base["pa_vs_R"] = pa_R
    base["k_pct_vs_R"] = (k_R / pa_R.replace(0, np.nan)).fillna(base["k_pct"])
    base["xwoba_vs_R"] = (xwoba_R / pa_R.replace(0, np.nan)).fillna(base["xwoba"])

    # Clean name and batting hand
    names, bats = [], []
    stand_obs = df_b.groupby("batter")["stand"].agg(lambda s: "S" if s.nunique() > 1 else s.iloc[0])
    for bid in base.index:
        b_info = people.get(str(bid))
        if b_info and b_info.get("name"):
            names.append(b_info["name"])
        else:
            names.append(str(bid))
        bats.append(b_info.get("bats") if b_info and b_info.get("bats") else stand_obs.get(bid, "R"))

    base["name"] = names
    base["bats"] = bats

    return base.sort_values("pa", ascending=False)


def extract_matchups(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate direct Batter vs. Pitcher matchup history."""
    pa_df = df[df["is_pa"] == 1].copy()
    bvp = pa_df.groupby(["pitcher", "batter"]).agg(
        pa=("events", "count"),
        k=("is_k", "sum"),
        bb=("is_bb", "sum"),
        h=("is_h", "sum"),
        hr=("is_hr", "sum"),
        single=("is_single", "sum"),
        double=("is_double", "sum"),
        triple=("is_triple", "sum"),
        woba_sum=("woba_value", "sum"),
        xwoba_sum=("xwoba_val", "sum"),
        delta_re=("delta_run_exp", "sum"),
    ).reset_index()

    bvp["woba"] = bvp["woba_sum"] / bvp["pa"]
    bvp["xwoba"] = bvp["xwoba_sum"] / bvp["pa"]
    bvp["k_pct"] = bvp["k"] / bvp["pa"]
    bvp["bb_pct"] = bvp["bb"] / bvp["pa"]
    return bvp


def compute_pitcher_similarity(
    pitchers_df: pd.DataFrame,
    target_pitcher_id: int,
    top_k: int = 10,
    enforce_throws: bool = True,
    custom_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Find the top-K most similar pitchers to a target pitcher using normalized Euclidean distance."""
    if target_pitcher_id not in pitchers_df.index:
        raise KeyError(f"Pitcher id {target_pitcher_id} not found in pitchers table.")

    target = pitchers_df.loc[target_pitcher_id]
    candidates = pitchers_df.copy()

    if enforce_throws:
        candidates = candidates[candidates["throws"] == target["throws"]].copy()

    cols = [c for c in PITCHER_SIM_COLS if c in candidates.columns]
    X = candidates[cols].to_numpy()

    # Apply feature weighting if specified
    weights = np.ones(len(cols), dtype=np.float64)
    if custom_weights:
        for i, col in enumerate(cols):
            if col in custom_weights:
                weights[i] = custom_weights[col]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X) * weights

    target_idx = list(candidates.index).index(target_pitcher_id)
    target_vec = X_scaled[target_idx]

    distances = np.linalg.norm(X_scaled - target_vec, axis=1)
    # Cosine/Gaussian similarity kernel: S = exp(-0.5 * (d / scale)^2)
    scale = np.median(distances[distances > 0]) if any(distances > 0) else 1.0
    sims = np.exp(-0.5 * (distances / scale) ** 2)

    res = candidates[["name", "throws", "pitches", "k_pct", "xwoba", "velo_fb"]].copy()
    res["distance"] = distances
    res["similarity"] = sims

    # Exclude the pitcher themselves and return top K
    res = res[res.index != target_pitcher_id].sort_values("distance", ascending=True)
    return res.head(top_k)


def compute_batter_similarity(
    batters_df: pd.DataFrame,
    target_batter_id: int,
    top_k: int = 15,
    enforce_bats: bool = True,
    custom_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Find the top-K most similar batters to a target batter using normalized Euclidean distance."""
    if target_batter_id not in batters_df.index:
        raise KeyError(f"Batter id {target_batter_id} not found in batters table.")

    target = batters_df.loc[target_batter_id]
    candidates = batters_df.copy()

    if enforce_bats and target["bats"] in {"R", "L"}:
        candidates = candidates[candidates["bats"] == target["bats"]].copy()

    cols = [c for c in BATTER_SIM_COLS if c in candidates.columns]
    X = candidates[cols].to_numpy()

    weights = np.ones(len(cols), dtype=np.float64)
    if custom_weights:
        for i, col in enumerate(cols):
            if col in custom_weights:
                weights[i] = custom_weights[col]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X) * weights

    target_idx = list(candidates.index).index(target_batter_id)
    target_vec = X_scaled[target_idx]

    distances = np.linalg.norm(X_scaled - target_vec, axis=1)
    scale = np.median(distances[distances > 0]) if any(distances > 0) else 1.0
    sims = np.exp(-0.5 * (distances / scale) ** 2)

    res = candidates[["name", "bats", "pa", "k_pct", "xwoba", "hard_hit_pct"]].copy()
    res["distance"] = distances
    res["similarity"] = sims

    res = res[res.index != target_batter_id].sort_values("distance", ascending=True)
    return res.head(top_k)


def pool_archetype_matchups(
    matchups_df: pd.DataFrame,
    similar_pitchers: pd.DataFrame,
    similar_batters: pd.DataFrame,
) -> dict[str, float]:
    """Combine and weight all historical matchups between the pitcher and batter similarity pools.
    
    Transforms tiny single-matchup samples (0-15 PA) into large, statistically stable
    archetype samples (500-2,000+ PA).
    """
    p_weights = similar_pitchers["similarity"].to_dict()
    b_weights = similar_batters["similarity"].to_dict()

    p_ids = set(p_weights.keys())
    b_ids = set(b_weights.keys())

    sub = matchups_df[matchups_df["pitcher"].isin(p_ids) & matchups_df["batter"].isin(b_ids)].copy()

    if sub.empty:
        return {
            "pooled_pa": 0,
            "effective_pa": 0.0,
            "pooled_xwoba": LEAGUE_DEFAULTS["xwoba"],
            "pooled_k_pct": LEAGUE_DEFAULTS["k_pct"],
            "pooled_bb_pct": LEAGUE_DEFAULTS["bb_pct"],
            "pooled_hr_pct": 0.03,
            "pooled_re_per_pa": 0.0,
        }

    # Weight of each PA is product of pitcher similarity and batter similarity
    sub["pair_weight"] = [
        p_weights[p] * b_weights[b] for p, b in zip(sub["pitcher"], sub["batter"])
    ]

    total_pa = int(sub["pa"].sum())
    eff_pa = float((sub["pair_weight"] * sub["pa"]).sum())
    w_sum = sub["pair_weight"] * sub["pa"]
    total_w = w_sum.sum()

    if total_w <= 0:
        total_w = 1.0

    pooled_xwoba = float((sub["pair_weight"] * sub["xwoba_sum"]).sum() / total_w)
    pooled_k_pct = float((sub["pair_weight"] * sub["k"]).sum() / total_w)
    pooled_bb_pct = float((sub["pair_weight"] * sub["bb"]).sum() / total_w)
    pooled_hr_pct = float((sub["pair_weight"] * sub["hr"]).sum() / total_w)
    pooled_re_per_pa = float((sub["pair_weight"] * sub["delta_re"]).sum() / total_w)

    return {
        "pooled_pa": total_pa,
        "effective_pa": round(eff_pa, 1),
        "pooled_xwoba": round(pooled_xwoba, 4),
        "pooled_k_pct": round(pooled_k_pct, 4),
        "pooled_bb_pct": round(pooled_bb_pct, 4),
        "pooled_hr_pct": round(pooled_hr_pct, 4),
        "pooled_re_per_pa": round(pooled_re_per_pa, 4),
    }
