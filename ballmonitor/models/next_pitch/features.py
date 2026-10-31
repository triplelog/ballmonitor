"""As-of features for the next_pitch study: for every pitch, only what was known before it.

Pitcher history features are recency-weighted pitch-type counts in several contexts, updated
after every pitch (so they include earlier pitches of the same game). Batter features are
recency-weighted rates from previous days only. Used by research.py; needs numpy + pandas.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ballmonitor.models.next_pitch.pitches import GBM_SPECS, VOCAB

K = len(VOCAB)
RES_CODES = ["B", "C", "S", "F", "X", "H"]
NONE_TYPE = K  # index used for "no previous pitch"
NONE_RES = len(RES_CODES)

# Context specs: the model's GBM_SPECS, with each level mapped to its column here.
LEVEL_COLUMNS = {"count": "count", "stand": "stand_i", "prev_type": "prev_t", "prev_result": "prev_r",
                 "prev2_type": "prev2_t", "batter": "batter", "game": "game_pk", "game_prev_type": "game_prev_t"}
SPECS = {name: tuple(LEVEL_COLUMNS[l] for l in spec) for name, spec in GBM_SPECS.items()}
FAMILY = {"FF": "fb", "SI": "fb", "FC": "fb", "SL": "br", "ST": "br", "SV": "br", "CU": "br", "KC": "br",
          "CH": "os", "FS": "os", "FO": "os", "KN": "os", "EP": "os", "SC": "os"}


def load_pitches(data_dir: Path, seasons: list[int]) -> pd.DataFrame:
    frames = [pd.read_parquet(data_dir / "pitches" / f"{s}.parquet") for s in seasons
              if (data_dir / "pitches" / f"{s}.parquet").exists()]
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["day", "game_pk", "at_bat_number", "pitch_number"], kind="stable").reset_index(drop=True)
    tidx = {t: i for i, t in enumerate(VOCAB)}
    ridx = {r: i for i, r in enumerate(RES_CODES)}
    df["y"] = df["pt"].map(tidx).astype(np.int8)
    df["count"] = (df["balls"].clip(0, 3) * 3 + df["strikes"].clip(0, 2)).astype(np.int8)
    df["stand_i"] = (df["stand"] == "L").astype(np.int8)
    df["throws_i"] = (df["p_throws"] == "L").astype(np.int8)
    for col, src in [("prev_t", "prev_type"), ("prev2_t", "prev2_type"), ("game_prev_t", "game_prev_type")]:
        df[col] = df[src].map(tidx).fillna(NONE_TYPE).astype(np.int8)
    for col, src in [("prev_r", "prev_result"), ("prev2_r", "prev2_result"), ("game_prev_r", "game_prev_result")]:
        df[col] = df[src].map(ridx).fillna(NONE_RES).astype(np.int8)
    return df


def pitcher_counts(df: pd.DataFrame, specs: dict[str, tuple], half_life: float,
                   rows: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Online recency-weighted counts: for each spec an (m, K) float32 array of counts *before*
    each pitch, for the pitches in `rows` (default: all). Every pitch still updates the tables."""
    n = len(df)
    store = np.full(n, -1, np.int64)
    rows = np.arange(n) if rows is None else np.asarray(rows)
    store[rows] = np.arange(len(rows))
    store_l = store.tolist()
    names = list(specs)
    comps = {c: df[c].to_numpy() for s in specs.values() for c in s}
    pitcher = df["pitcher"].to_numpy()
    y = df["y"].to_numpy()
    day = df["day"].to_numpy().astype(np.float64)
    inflate = np.exp2(day / half_life) if half_life > 0 else np.ones(n)
    comp_lists = {c: v.tolist() for c, v in comps.items()}
    spec_cols = [[comp_lists[c] for c in specs[name]] for name in names]
    out = {name: np.zeros((len(rows), K), np.float32) for name in names}
    outs = [out[name] for name in names]
    tables: dict = {}
    # Tables hold counts in "inflated" units 2^(day/half_life) (float64, fine up to ~2^1000), and are
    # scaled back to the current day before storing, so float32 outputs never overflow.
    pitcher_l, y_l, inflate_l = pitcher.tolist(), y.tolist(), inflate.tolist()
    for i in range(n):
        pid, t, w, j = pitcher_l[i], y_l[i], inflate_l[i], store_l[i]
        sc = 1.0 / w
        for s, cols in enumerate(spec_cols):
            key = (pid, s, *[c[i] for c in cols])
            row = tables.get(key)
            if row is None:
                row = tables[key] = [0.0] * K
            elif j >= 0:
                outs[s][j] = [v * sc for v in row]
            row[t] += w
    return out


def batter_features(df: pd.DataFrame, half_life: float = 365.0, final: bool = False) -> pd.DataFrame:
    """Recency-weighted batter rates from previous days only (league average where no data).

    final=True instead returns one row per batter with the rates after the last day (index = batter id)."""
    cols = ["pa", "woba_n", "woba_d", "k", "bb", "swings", "whiffs", "oz", "oz_swings",
            "seen_R", "fb_R", "br_R", "os_R", "seen_L", "fb_L", "br_L", "os_L", "hits", "tb", "ab"]
    idx = {c: j for j, c in enumerate(cols)}
    ev = df["events"].fillna("").to_numpy()
    fam = df["pt"].map(FAMILY).to_numpy()
    hand = df["p_throws"].to_numpy()
    tb_map = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
    not_ab = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt", "sac_fly_double_play",
              "sac_bunt_double_play", "catcher_interf", "truncated_pa"}
    contrib = np.zeros((len(df), len(cols)), np.float64)
    is_pa = ev != ""
    contrib[:, idx["pa"]] = is_pa
    contrib[:, idx["woba_n"]] = np.where(is_pa, df["woba_value"].fillna(0).to_numpy(), 0)
    contrib[:, idx["woba_d"]] = np.where(is_pa, df["woba_denom"].fillna(0).to_numpy(), 0)
    contrib[:, idx["k"]] = np.char.startswith(ev.astype(str), "strikeout")
    contrib[:, idx["bb"]] = np.isin(ev, ["walk", "intent_walk"])
    contrib[:, idx["hits"]] = np.isin(ev, list(tb_map))
    contrib[:, idx["tb"]] = pd.Series(ev).map(tb_map).fillna(0).to_numpy()
    contrib[:, idx["ab"]] = is_pa & ~np.isin(ev, list(not_ab))
    contrib[:, idx["swings"]] = df["swing"].to_numpy()
    contrib[:, idx["whiffs"]] = df["whiff"].to_numpy()
    oz = (df["in_zone"].to_numpy() == 0)
    contrib[:, idx["oz"]] = oz
    contrib[:, idx["oz_swings"]] = oz & (df["swing"].to_numpy() == 1)
    for h in ("R", "L"):
        m = hand == h
        contrib[:, idx[f"seen_{h}"]] = m
        for f in ("fb", "br", "os"):
            contrib[:, idx[f"{f}_{h}"]] = m & (fam == f)

    batter = df["batter"].to_numpy()
    day = df["day"].to_numpy()
    state: dict[int, np.ndarray] = {}
    last_day: dict[int, int] = {}
    snap = np.zeros((len(df), len(cols)), np.float32)
    decay = np.log(2) / half_life
    order = np.argsort(day, kind="stable")
    bounds = np.flatnonzero(np.diff(day[order])) + 1
    for block in np.split(order, bounds):
        d = int(day[block[0]])
        bat_block = batter[block]
        for b in np.unique(bat_block):
            s = state.get(b)
            if s is not None:
                s *= np.exp(-decay * (d - last_day[b]))
                last_day[b] = d
        for j, b in zip(block, bat_block):
            s = state.get(b)
            if s is not None:
                snap[j] = s
        sums = pd.DataFrame(contrib[block]).groupby(bat_block).sum()
        for b, vals in zip(sums.index, sums.to_numpy()):
            if b in state:
                state[b] += vals
            else:
                state[b] = vals.copy()
                last_day[b] = d

    if final:
        end = int(day.max()) + 1
        ids = list(state)
        snap = np.stack([state[b] * np.exp(-decay * (end - last_day[b])) for b in ids]).astype(np.float32)
        hand = np.full(len(ids), "R")  # rows below are per pitcher hand; both returned
    S = pd.DataFrame(snap, columns=cols)
    lg = contrib.sum(axis=0)
    L = dict(zip(cols, lg))
    prior = 50.0  # pseudo-events of league average, so thin samples aren't extreme

    def rate(num, den, lnum, lden):
        return ((S[num] + prior * L[lnum] / L[lden]) / (S[den] + prior)).astype(np.float32)

    out = pd.DataFrame({
        "bat_pa": S["pa"],
        "bat_woba": rate("woba_n", "woba_d", "woba_n", "woba_d"),
        "bat_k": rate("k", "pa", "k", "pa"),
        "bat_bb": rate("bb", "pa", "bb", "pa"),
        "bat_whiff": rate("whiffs", "swings", "whiffs", "swings"),
        "bat_chase": rate("oz_swings", "oz", "oz_swings", "oz"),
        "bat_slg": rate("tb", "ab", "tb", "ab"),
    })
    hand_l = (hand == "L")
    for f in ("fb", "br", "os"):
        r = rate(f"{f}_R", "seen_R", f"{f}_R", "seen_R")
        l = rate(f"{f}_L", "seen_L", f"{f}_L", "seen_L")
        if final:
            out[f"bat_seen_{f}_vsR"], out[f"bat_seen_{f}_vsL"] = r, l
        else:
            out[f"bat_seen_{f}"] = np.where(hand_l, l, r).astype(np.float32)
    if final:
        out.index = ids
    return out


def league_batter(df: pd.DataFrame) -> dict[str, float]:
    """League-average batter feature values (used when no batter is given)."""
    b = batter_features(df.iloc[-200_000:])
    return {c: float(b[c].median()) for c in b.columns}
