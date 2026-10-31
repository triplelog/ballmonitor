"""Build next_pitch datasets from the cached Statcast day files (see fetch.py for outputs).

Needs pandas + pyarrow (`pip install -e '.[data]'`). model.py itself only reads the CSVs.
"""

from __future__ import annotations

import csv
import gzip
import json
import random
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ballmonitor.models.next_pitch.pitches import RESULTS, normalize_type

EPOCH = date(2021, 1, 1)
PEOPLE = "https://statsapi.mlb.com/api/v1/people?personIds={ids}"
HIT_TB = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
WALKS = {"walk", "intent_walk"}
NOT_AB = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt", "sac_fly_double_play",
          "sac_bunt_double_play", "catcher_interf", "truncated_pa"}
SWING = {"S", "F", "X"}
PITCHER_FILE_COLS = ["date", "game_pk", "ab", "pn", "balls", "strikes", "stand", "pt", "res",
                     "outs", "runners", "tto", "batter"]
MIN_PITCHER_PITCHES = 100  # pitchers below this are left out of data/pitchers/
BACKTEST_SEASON, BACKTEST_PITCHERS, BACKTEST_PER_PITCHER = 2026, 25, 60


def load_season(raw_days: Path, season: int) -> pd.DataFrame:
    files = sorted(raw_days.glob(f"{season}-*.csv.gz"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f, dtype={"pitch_type": str, "description": str, "events": str}) for f in files],
                   ignore_index=True)
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"], kind="stable").reset_index(drop=True)
    return df


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Drop non-pitches and add model columns. Keeps PA-ending events of dropped rows in `pa_events`."""
    df = df.copy()
    df["pt"] = [normalize_type(c if isinstance(c, str) else None) for c in df["pitch_type"]]
    df["res"] = df["description"].map(RESULTS).fillna("B")
    df["date"] = pd.to_datetime(df["game_date"]).dt.date
    df["day"] = [(d - EPOCH).days for d in df["date"]]
    df["game_year"] = [d.year for d in df["date"]]
    pitches = df[df["pt"].notna()].copy()

    ab = ["game_pk", "at_bat_number"]
    g_ab = pitches.groupby(ab, sort=False)
    pitches["ab_idx"] = g_ab.cumcount()
    for col, src in [("prev_type", "pt"), ("prev_result", "res"), ("prev_x", "plate_x"),
                     ("prev_z", "plate_z"), ("prev_speed", "release_speed"), ("prev_zone", "zone")]:
        pitches[col] = g_ab[src].shift(1)
    pitches["prev2_type"] = g_ab["pt"].shift(2)
    pitches["prev2_result"] = g_ab["res"].shift(2)

    g_game = pitches.groupby(["game_pk", "pitcher"], sort=False)
    pitches["game_pitch_n"] = g_game.cumcount()
    pitches["game_prev_type"] = g_game["pt"].shift(1)  # previous pitch by this pitcher in the game
    pitches["game_prev_result"] = g_game["res"].shift(1)
    first = pitches["ab_idx"] == 0
    pitches["batters_faced"] = first.astype(int).groupby([pitches["game_pk"], pitches["pitcher"]]).cumsum() - 1
    pitches["runners"] = pitches[["on_1b", "on_2b", "on_3b"]].sum(axis=1)
    pitches["score_diff"] = pitches["fld_score"] - pitches["bat_score"]
    pitches["swing"] = pitches["res"].isin(SWING).astype(int)
    pitches["whiff"] = (pitches["res"] == "S").astype(int)
    pitches["csw"] = pitches["res"].isin({"S", "C"}).astype(int)
    pitches["in_zone"] = pitches["zone"].between(1, 9).astype(int)
    return pitches.reset_index(drop=True)


def people(raw: Path, ids: set[int]) -> dict[int, dict]:
    path = raw / "people.json"
    known = {int(k): v for k, v in json.loads(path.read_text()).items()} if path.exists() else {}
    missing = sorted(i for i in ids if i not in known)
    for start in range(0, len(missing), 150):
        chunk = missing[start:start + 150]
        url = PEOPLE.format(ids=",".join(map(str, chunk)))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as res:
                for p in json.loads(res.read()).get("people", []):
                    known[p["id"]] = {"name": p.get("fullName", ""), "bats": p.get("batSide", {}).get("code", ""),
                                      "throws": p.get("pitchHand", {}).get("code", "")}
        except Exception:
            pass  # names are cosmetic; ids still work
    path.write_text(json.dumps({str(k): v for k, v in known.items()}))
    return known


def batter_stats(raw_all: pd.DataFrame, pitches: pd.DataFrame, since_day: int) -> pd.DataFrame:
    """Rolling batter stats over plate appearances/pitches with day >= since_day."""
    pa = raw_all[(raw_all["day"] >= since_day) & raw_all["events"].notna() & (raw_all["events"] != "")]
    ev = pa["events"]
    hits = ev.isin(HIT_TB)
    agg = pd.DataFrame({
        "batter": pa["batter"], "pa": 1, "h": hits.astype(int), "tb": ev.map(HIT_TB).fillna(0),
        "bb": ev.isin(WALKS).astype(int), "hbp": (ev == "hit_by_pitch").astype(int),
        "sf": ev.str.startswith("sac_fly").astype(int), "ab": (~ev.isin(NOT_AB)).astype(int),
        "k": ev.str.startswith("strikeout").astype(int),
        "woba": pa["woba_value"].fillna(0), "woba_d": pa["woba_denom"].fillna(0),
    }).groupby("batter").sum()
    p = pitches[pitches["day"] >= since_day]
    out_zone = p["in_zone"] == 0
    sw = pd.DataFrame({
        "batter": p["batter"], "swings": p["swing"], "whiffs": p["whiff"],
        "chase_swings": p["swing"] * out_zone, "out_zone": out_zone.astype(int),
        "fastballs": p["pt"].isin({"FF", "SI", "FC"}).astype(int), "seen": 1,
    }).groupby("batter").sum()
    t = agg.join(sw, how="outer").fillna(0)
    obp_d = (t["ab"] + t["bb"] + t["hbp"] + t["sf"]).replace(0, np.nan)
    t["obp"] = (t["h"] + t["bb"] + t["hbp"]) / obp_d
    t["slg"] = t["tb"] / t["ab"].replace(0, np.nan)
    t["ops"] = t["obp"] + t["slg"]
    t["woba"] = t["woba"] / t["woba_d"].replace(0, np.nan)
    t["k_pct"] = t["k"] / t["pa"].replace(0, np.nan)
    t["whiff_pct"] = t["whiffs"] / t["swings"].replace(0, np.nan)
    t["chase_pct"] = t["chase_swings"] / t["out_zone"].replace(0, np.nan)
    t["fastball_pct_seen"] = t["fastballs"] / t["seen"].replace(0, np.nan)
    return t


def build_all(model_dir: Path) -> list[str]:
    data = model_dir / "data"
    raw = data / "raw"
    (data / "pitches").mkdir(parents=True, exist_ok=True)
    (data / "pitchers").mkdir(parents=True, exist_ok=True)
    log = []
    seasons, raws = {}, []
    from ballmonitor.models.next_pitch.fetch import SEASONS

    for season in SEASONS:
        raw_df = load_season(raw / "days", season)
        if raw_df.empty:
            continue
        pitches = derive(raw_df)
        pitches.to_parquet(data / "pitches" / f"{season}.parquet", index=False)
        raw_df["day"] = [(d - EPOCH).days for d in pd.to_datetime(raw_df["game_date"]).dt.date]
        raws.append(raw_df[["batter", "day", "events", "woba_value", "woba_denom"]])
        seasons[season] = pitches
        log.append(f"pitches/{season}.parquet: {len(pitches):,} pitches, {pitches['pitcher'].nunique()} pitchers")

    allp = pd.concat(seasons.values(), ignore_index=True)
    ids = set(allp["pitcher"].unique()) | set(allp["batter"].unique())
    names = people(raw, {int(i) for i in ids})

    # per-pitcher history files + index
    counts = allp.groupby(["pitcher", "game_year"]).size().unstack(fill_value=0)
    keep = counts.index[counts.sum(axis=1) >= MIN_PITCHER_PITCHES]
    hist = allp[allp["pitcher"].isin(keep)].assign(
        ab=allp["at_bat_number"], pn=allp["pitch_number"], outs=allp["outs_when_up"],
        tto=allp["n_thruorder_pitcher"].fillna(1).astype(int))
    hist = hist.sort_values(["date", "game_pk", "at_bat_number", "pitch_number"], kind="stable")
    hist["date"] = hist["date"].astype(str)
    for pid, g in hist.groupby("pitcher"):
        with gzip.open(data / "pitchers" / f"{pid}.csv.gz", "wt", newline="") as fh:
            g[PITCHER_FILE_COLS].to_csv(fh, index=False)
    last_hand = allp.groupby("pitcher")["p_throws"].last()
    with open(data / "pitchers.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pitcher_id", "name", "throws", "total"] + [f"pitches_{s}" for s in counts.columns])
        for pid in sorted(keep, key=lambda i: -counts.loc[i].sum()):
            row = counts.loc[pid]
            w.writerow([pid, names.get(int(pid), {}).get("name", ""), last_hand[pid], int(row.sum())] + [int(v) for v in row])
    log.append(f"pitchers/: {len(keep)} pitchers with >= {MIN_PITCHER_PITCHES} pitches; index in pitchers.csv")

    # batter table: last 365 days of plain stats + the model's recency-weighted features
    from ballmonitor.models.next_pitch import features as F

    raw_all = pd.concat(raws, ignore_index=True)
    last_day = int(allp["day"].max())
    bs = batter_stats(raw_all, allp, last_day - 365)
    stand = allp.groupby("batter")["stand"].agg(lambda s: "S" if s.nunique() > 1 else s.iloc[0])
    fdf = F.load_pitches(data, list(seasons))
    feats = F.batter_features(fdf, final=True)
    fcols = list(feats.columns)
    cols = ["pa", "ops", "woba", "k_pct", "whiff_pct", "chase_pct", "fastball_pct_seen"]
    with open(data / "batters.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["batter_id", "name", "bats"] + cols + fcols)
        for bid, r in bs[bs["pa"] >= 1].sort_values("pa", ascending=False).iterrows():
            fr = feats.loc[bid] if bid in feats.index else None
            w.writerow([int(bid), names.get(int(bid), {}).get("name", ""), stand.get(bid, "")]
                       + [int(r["pa"])] + [("" if pd.isna(r[c]) else f"{r[c]:.3f}") for c in cols[1:]]
                       + [("" if fr is None else f"{fr[c]:.4f}") for c in fcols])
    log.append(f"batters.csv: {int((bs['pa'] >= 1).sum())} batters (plain stats over the last 365 days of data)")

    # meta.json: data end date, league prior by pitcher hand (warm-up season, as in research.py)
    meta_path = data / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    warm = fdf[fdf["game_year"] == min(seasons)]
    meta["last_date"] = str(allp["date"].max())
    meta["league_prior"] = {}
    for h in ("R", "L"):
        c = np.bincount(warm.loc[warm["p_throws"] == h, "y"], minlength=F.K) + 1.0
        meta["league_prior"][h] = [round(float(v), 6) for v in c / c.sum()]
    meta["batter_league"] = F.league_batter(fdf)
    meta_path.write_text(json.dumps(meta, indent=1))
    log.append(f"meta.json: data through {meta['last_date']}")

    log.append(build_backtest(data, fdf, names))
    return log


def sequence_string(types, results) -> str:
    return " ".join(f"{t}:{r}" for t, r in zip(types, results))


def build_backtest(data: Path, fdf: pd.DataFrame, names: dict) -> str:
    """Sample pitches from the busiest pitchers of BACKTEST_SEASON (fixed seed), with as-of inputs."""
    from ballmonitor.models.next_pitch import features as F

    season = fdf[fdf["game_year"] == BACKTEST_SEASON]
    if season.empty:
        return "backtest.csv: skipped (no backtest season data)"
    bat = F.batter_features(fdf).loc[season.index]
    top = season["pitcher"].value_counts().head(BACKTEST_PITCHERS).index
    rng = random.Random(BACKTEST_SEASON)
    rows = []
    for pid in top:
        g = season[season["pitcher"] == pid]
        for i in sorted(rng.sample(list(g.index), BACKTEST_PER_PITCHER)):
            r = fdf.loc[i]
            game = g[(g["game_pk"] == r["game_pk"]) & (g["game_pitch_n"] < r["game_pitch_n"])].sort_values("game_pitch_n")
            in_ab = game["at_bat_number"] == r["at_bat_number"]
            num = lambda v, f="{:.3f}": "" if pd.isna(v) else f.format(v)
            rows.append({
                "pitcher_id": int(pid), "pitcher": names.get(int(pid), {}).get("name", ""), "as_of": str(r["date"]),
                "balls": int(r["balls"]), "strikes": int(r["strikes"]), "stand": r["stand"],
                "sequence": sequence_string(game.loc[in_ab, "pt"], game.loc[in_ab, "res"]),
                "earlier_in_game": sequence_string(game.loc[~in_ab, "pt"], game.loc[~in_ab, "res"]),
                "outs": int(r["outs_when_up"]),
                "bases": "".join(b for b, c in zip("123", ["on_1b", "on_2b", "on_3b"]) if r[c]),
                "tto": int(r["n_thruorder_pitcher"] or 1), "inning": int(r["inning"]), "score_diff": int(r["score_diff"]),
                "pitch_count": int(r["game_pitch_n"]), "batters_faced": int(r["batters_faced"]),
                "days_rest": num(r["pitcher_days_since_prev_game"], "{:.0f}"),
                "prev_x": num(r["prev_x"]), "prev_z": num(r["prev_z"]), "prev_speed": num(r["prev_speed"], "{:.1f}"),
                "prev_zone": num(r["prev_zone"], "{:.0f}"), "batter_id": int(r["batter"]),
                **{c: f"{bat.loc[i, c]:.4f}" for c in bat.columns},
                "actual": r["pt"],
            })
    with open(data / "backtest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return (f"backtest.csv: {len(rows)} pitches ({BACKTEST_PER_PITCHER} each from the {BACKTEST_PITCHERS} busiest "
            f"{BACKTEST_SEASON} pitchers)")
