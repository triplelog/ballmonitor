"""Comprehensive benchmark of three advanced model upgrades on out-of-sample matchups:
1. VAA & Vertical Break / Ride vs. Sink features
2. Latent Factor Embeddings (Collaborative Filtering / Matrix Factorization)
3. Pitch-by-Pitch Micro-Simulation (Markov chain at-bat engine)
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse, stats
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import StandardScaler

from ballmonitor.core import registry
from ballmonitor.models.bvp_similarity import features as F

MODEL_DIR = Path(__file__).resolve().parent
DATA_DIR = MODEL_DIR / "data"

def run_study():
    print("Loading data...")
    backtest_df = pd.read_csv(DATA_DIR / "backtest.csv")
    pitchers_df = pd.read_parquet(DATA_DIR / "pitchers.parquet")
    batters_df = pd.read_parquet(DATA_DIR / "batters.parquet")
    matchups_df = pd.read_parquet(DATA_DIR / "matchups.parquet")

    actuals = backtest_df["observed_xwoba"].to_numpy()
    n_cases = len(backtest_df)
    print(f"Loaded {n_cases} holdout cases.")

    # -------------------------------------------------------------
    # 0. Load Current Shipped Models (Control and Base Similarity)
    # -------------------------------------------------------------
    m_base = registry.load_model("bvp_similarity")
    m_control = registry.load_model("bvp_similarity", variant="pure_baseline")

    preds_control = np.array([
        m_control.predict({"pitcher": str(r["pitcher"]), "batter": str(r["batter"])}).primary.estimate
        for _, r in backtest_df.iterrows()
    ])
    preds_base = np.array([
        m_base.predict({"pitcher": str(r["pitcher"]), "batter": str(r["batter"])}).primary.estimate
        for _, r in backtest_df.iterrows()
    ])

    # -------------------------------------------------------------
    # UPGRADE 1: VAA & Vertical Break / Ride vs. Sink Features
    # -------------------------------------------------------------
    print("\n--- Training Upgrade 1: VAA & Vertical Break ---")
    # Load pitches from 2021-2025 to extract vertical location and launch angle traits
    pitches_dir = F.find_pitches_dir(MODEL_DIR)
    train_pitches = F.load_pitches(pitches_dir, seasons=[2021, 2022, 2023, 2024, 2025])

    # Pitcher vertical break proxies:
    # 1. pct of 4-seamers in upper third (ride zone)
    # 2. whiff% on high 4-seamers
    # 3. pct of sinkers in lower third (drop/sink zone)
    # 4. ground ball rate on sinkers
    ff_mask = train_pitches["pt"] == "FF"
    si_mask = train_pitches["pt"] == "SI"
    high_mask = train_pitches["plate_z"] >= 2.8
    low_mask = train_pitches["plate_z"] <= 2.2

    train_pitches["is_ff"] = ff_mask.astype(int)
    train_pitches["is_si"] = si_mask.astype(int)
    train_pitches["ff_high"] = (ff_mask & high_mask).astype(int)
    train_pitches["si_low"] = (si_mask & low_mask).astype(int)
    train_pitches["whiff_high_ff"] = ((train_pitches["whiff"] == 1) & (train_pitches["ff_high"] == 1)).astype(int)
    train_pitches["swing_high_ff"] = ((train_pitches["swing"] == 1) & (train_pitches["ff_high"] == 1)).astype(int)

    p_vaa = train_pitches.groupby("pitcher").agg(
        ff_count=("is_ff", "sum"),
        ff_high_count=("ff_high", "sum"),
        whiff_high_ff=("whiff_high_ff", "sum"),
        swing_high_ff=("swing_high_ff", "sum"),
        si_count=("is_si", "sum"),
        si_low_count=("si_low", "sum"),
    )
    p_ride = pitchers_df.copy()
    p_ride["pct_ff_high"] = (p_vaa["ff_high_count"] / p_vaa["ff_count"].replace(0, np.nan)).reindex(p_ride.index).fillna(0.35)
    p_ride["whiff_high_ff"] = (p_vaa["whiff_high_ff"] / p_vaa["swing_high_ff"].replace(0, np.nan)).reindex(p_ride.index).fillna(0.24)
    p_ride["pct_si_low"] = (p_vaa["si_low_count"] / p_vaa["si_count"].replace(0, np.nan)).reindex(p_ride.index).fillna(0.42)

    # Batter vertical/launch angle proxies:
    # Mean launch angle and whiff rate on high fastballs
    b_la = train_pitches[train_pitches["launch_angle"].notna()].groupby("batter")["launch_angle"].mean()
    b_vaa = train_pitches.groupby("batter").agg(
        whiff_high_ff=("whiff_high_ff", "sum"),
        swing_high_ff=("swing_high_ff", "sum"),
    )
    b_ride = batters_df.copy()
    b_ride["avg_launch_angle"] = b_la.reindex(b_ride.index).fillna(12.5)
    b_ride["whiff_high_ff"] = (b_vaa["whiff_high_ff"] / b_vaa["swing_high_ff"].replace(0, np.nan)).reindex(b_ride.index).fillna(0.24)

    # Vertical similarity feature lists
    p_vaa_cols = F.PITCHER_SIM_COLS + ["pct_ff_high", "whiff_high_ff", "pct_si_low"]
    b_vaa_cols = F.BATTER_SIM_COLS + ["avg_launch_angle", "whiff_high_ff"]

    preds_vaa = []
    for _, row in backtest_df.iterrows():
        p_id = int(row["pitcher"])
        b_id = int(row["batter"])

        # Baseline Log5
        p_row = p_ride.loc[p_id]
        b_row = b_ride.loc[b_id]
        b_stand = "R" if b_row["bats"] == "R" else ("L" if b_row["bats"] == "L" else ("R" if p_row["throws"] == "L" else "L"))
        pb = float(b_row[f"xwoba_vs_{p_row['throws']}"])
        pp = float(p_row[f"xwoba_vs_{b_stand}"])
        pl = 0.315
        base_xwoba = (pb * pp / pl) / ((pb * pp / pl) + ((1 - pb) * (1 - pp) / (1 - pl)))

        # VAA-enhanced similarity
        sim_p = F.compute_pitcher_similarity(p_ride, p_id, top_k=8)
        sim_b = F.compute_batter_similarity(b_ride, b_id, top_k=12)
        arch = F.pool_archetype_matchups(matchups_df, sim_p, sim_b)

        # Direct BvP
        dir_m = matchups_df[(matchups_df["pitcher"] == p_id) & (matchups_df["batter"] == b_id)]
        n_dir = int(dir_m.iloc[0]["pa"]) if not dir_m.empty else 0
        y_dir = float(dir_m.iloc[0]["xwoba"]) if not dir_m.empty else base_xwoba

        w_dir = n_dir / (n_dir + 120.0)
        w_arch = min(0.50, (1 - w_dir) * (arch["effective_pa"] / (arch["effective_pa"] + 350.0)))
        pred = w_dir * y_dir + w_arch * arch["pooled_xwoba"] + (1 - w_dir - w_arch) * base_xwoba
        preds_vaa.append(pred)

    preds_vaa = np.array(preds_vaa)

    # -------------------------------------------------------------
    # UPGRADE 2: Latent Factor Collaborative Filtering (SVD)
    # -------------------------------------------------------------
    print("\n--- Training Upgrade 2: Latent Factor SVD Embeddings ---")
    valid_p = list(pitchers_df.index)
    valid_b = list(batters_df.index)
    p_map = {pid: i for i, pid in enumerate(valid_p)}
    b_map = {bid: j for j, bid in enumerate(valid_b)}

    sub_m = matchups_df[matchups_df["pitcher"].isin(p_map) & matchups_df["batter"].isin(b_map)].copy()
    sub_m["weight"] = sub_m["pa"] / (sub_m["pa"] + 10.0)
    sub_m["shrunk_delta"] = (sub_m["xwoba"] - 0.315) * sub_m["weight"]

    mat = sparse.csr_matrix(
        (sub_m["shrunk_delta"].values,
         ([p_map[pid] for pid in sub_m["pitcher"]], [b_map[bid] for bid in sub_m["batter"]])),
        shape=(len(valid_p), len(valid_b))
    )
    svd = TruncatedSVD(n_components=12, random_state=42)
    P_latent = svd.fit_transform(mat)
    Q_latent = svd.components_.T

    # Normalize latent vectors for cosine distance
    P_norm = P_latent / (np.linalg.norm(P_latent, axis=1, keepdims=True) + 1e-8)
    Q_norm = Q_latent / (np.linalg.norm(Q_latent, axis=1, keepdims=True) + 1e-8)

    preds_latent = []
    for _, row in backtest_df.iterrows():
        p_id = int(row["pitcher"])
        b_id = int(row["batter"])
        p_idx = p_map[p_id]
        b_idx = b_map[b_id]

        p_row = pitchers_df.loc[p_id]
        b_row = batters_df.loc[b_id]
        b_stand = "R" if b_row["bats"] == "R" else ("L" if b_row["bats"] == "L" else ("R" if p_row["throws"] == "L" else "L"))
        pb = float(b_row[f"xwoba_vs_{p_row['throws']}"])
        pp = float(p_row[f"xwoba_vs_{b_stand}"])
        pl = 0.315
        base_xwoba = (pb * pp / pl) / ((pb * pp / pl) + ((1 - pb) * (1 - pp) / (1 - pl)))

        # Find latent neighbors of same hand
        p_hand = p_row["throws"]
        same_hand_p_mask = (pitchers_df["throws"] == p_hand).values
        same_hand_p_indices = np.where(same_hand_p_mask)[0]
        
        sims_p = P_norm[same_hand_p_indices] @ P_norm[p_idx]
        top_p_order = np.argsort(-sims_p)[1:9]
        top_p_ids = [valid_p[same_hand_p_indices[idx]] for idx in top_p_order]
        top_p_sims = sims_p[top_p_order]

        b_bats = b_row["bats"]
        same_bats_b_mask = (batters_df["bats"] == b_bats).values if b_bats in {"R", "L"} else np.ones(len(valid_b), dtype=bool)
        same_bats_b_indices = np.where(same_bats_b_mask)[0]

        sims_b = Q_norm[same_bats_b_indices] @ Q_norm[b_idx]
        top_b_order = np.argsort(-sims_b)[1:13]
        top_b_ids = [valid_b[same_bats_b_indices[idx]] for idx in top_b_order]
        top_b_sims = sims_b[top_b_order]

        df_sim_p = pd.DataFrame({"similarity": np.clip(top_p_sims, 0.1, 1.0)}, index=top_p_ids)
        df_sim_b = pd.DataFrame({"similarity": np.clip(top_b_sims, 0.1, 1.0)}, index=top_b_ids)
        arch = F.pool_archetype_matchups(matchups_df, df_sim_p, df_sim_b)

        # Latent interaction dot product
        latent_delta = float(P_latent[p_idx] @ Q_latent[b_idx])

        dir_m = matchups_df[(matchups_df["pitcher"] == p_id) & (matchups_df["batter"] == b_id)]
        n_dir = int(dir_m.iloc[0]["pa"]) if not dir_m.empty else 0
        y_dir = float(dir_m.iloc[0]["xwoba"]) if not dir_m.empty else base_xwoba

        w_dir = n_dir / (n_dir + 120.0)
        w_arch = min(0.50, (1 - w_dir) * (arch["effective_pa"] / (arch["effective_pa"] + 350.0)))
        
        pred = w_dir * y_dir + w_arch * arch["pooled_xwoba"] + (1 - w_dir - w_arch) * (base_xwoba + latent_delta * 0.4)
        preds_latent.append(pred)

    preds_latent = np.array(preds_latent)

    # -------------------------------------------------------------
    # UPGRADE 3: Pitch-by-Pitch Micro-Simulation (Markov Model)
    # -------------------------------------------------------------
    print("\n--- Training Upgrade 3: Pitch-by-Pitch Micro-Simulation ---")
    preds_microsim = []
    
    # Pre-solve pitch-by-pitch absorbing state transition matrix
    for _, row in backtest_df.iterrows():
        p_id = int(row["pitcher"])
        b_id = int(row["batter"])
        p_row = pitchers_df.loc[p_id]
        b_row = batters_df.loc[b_id]

        # 1. Pitch in-zone probability
        p_zone = float(p_row["zone_pct"])
        
        # 2. Swing rates
        z_swing = 0.68
        chase = float(b_row["chase_pct"])
        p_swing_in = z_swing
        p_swing_out = chase
        p_swing = p_zone * p_swing_in + (1 - p_zone) * p_swing_out

        # 3. Whiff rate weighted by pitcher arsenal
        # Weighted whiff across FF, BR, OS
        pct_fb = float(p_row["pct_ff"] + p_row["pct_si"] + p_row["pct_fc"])
        pct_br = float(p_row["pct_sl"] + p_row["pct_st"] + p_row["pct_cu"])
        pct_os = float(p_row["pct_ch"] + p_row["pct_fs"])

        whiff_fb = (float(b_row["whiff_fb"]) + float(p_row["whiff_pct"])) / 2.0
        whiff_br = (float(b_row["whiff_br"]) + float(p_row["whiff_pct"])) / 2.0
        whiff_os = (float(b_row["whiff_os"]) + float(p_row["whiff_pct"])) / 2.0
        p_whiff_swing = pct_fb * whiff_fb + pct_br * whiff_br + pct_os * whiff_os

        # Outcomes per pitch
        p_whiff = p_swing * p_whiff_swing
        p_foul = p_swing * (1 - p_whiff_swing) * 0.50
        p_bip = p_swing * (1 - p_whiff_swing) * 0.50
        p_called_strike = (1 - p_swing) * p_zone
        p_ball = (1 - p_swing) * (1 - p_zone)

        # Micro-simulation count state dynamic programming
        # Value of state (b, s): probability of (K, BB, BIP)
        # Using memoization on (b, s)
        memo = {}
        def get_state(b, s):
            if (b, s) in memo:
                return memo[(b, s)]
            if b >= 4:
                return np.array([0.0, 1.0, 0.0]) # BB
            if s >= 3:
                return np.array([1.0, 0.0, 0.0]) # K

            # From (b, s), next pitch probabilities:
            # Ball -> (b+1, s)
            # Called strike or whiff -> (b, s+1)
            # Foul -> (b, s+1) if s < 2 else (b, 2)
            # BIP -> absorbing BIP
            p_strike = p_called_strike + p_whiff
            res = p_bip * np.array([0.0, 0.0, 1.0]) + p_ball * get_state(b + 1, s)
            
            if s < 2:
                res += (p_strike + p_foul) * get_state(b, s + 1)
            else:
                # With 2 strikes, fouls don't advance strike count
                # Let V = outcome from (b, 2). Then V = (p_bip*BIP + p_ball*V_b+1 + p_strike*K) / (1 - p_foul)
                res_strike = p_strike * np.array([1.0, 0.0, 0.0])
                res = (res + res_strike) / (1.0 - p_foul)

            memo[(b, s)] = res
            return res

        pk, pbb, pbip = get_state(0, 0)

        # Expected xwOBA on BIP
        xwoba_bip = (float(b_row["xwoba"]) - 0.69 * float(b_row["bb_pct"])) / max(0.1, 1.0 - float(b_row["k_pct"]) - float(b_row["bb_pct"]))
        xwoba_bip = np.clip(xwoba_bip, 0.280, 0.460)

        pred_sim = pbb * 0.69 + pbip * xwoba_bip
        
        # Blend micro-sim with baseline
        b_stand = "R" if b_row["bats"] == "R" else ("L" if b_row["bats"] == "L" else ("R" if p_row["throws"] == "L" else "L"))
        pb = float(b_row[f"xwoba_vs_{p_row['throws']}"])
        pp = float(p_row[f"xwoba_vs_{b_stand}"])
        base_xw = (pb * pp / 0.315) / ((pb * pp / 0.315) + ((1 - pb) * (1 - pp) / (1 - 0.315)))

        pred_blended = 0.40 * pred_sim + 0.60 * base_xw
        preds_microsim.append(pred_blended)

    preds_microsim = np.array(preds_microsim)

    # -------------------------------------------------------------
    # STATISTICAL EVALUATION ACROSS ALL 5 MODELS
    # -------------------------------------------------------------
    models = {
        "Control (Log5 Baseline)": preds_control,
        "Shipped Base (k-NN)": preds_base,
        "Upgrade 1: VAA & Vertical Break": preds_vaa,
        "Upgrade 2: Latent Embeddings (SVD)": preds_latent,
        "Upgrade 3: Pitch-by-Pitch Micro-Sim": preds_microsim,
    }

    results = []
    for name, p_vec in models.items():
        ae = np.abs(p_vec - actuals)
        se = (p_vec - actuals) ** 2
        bias = np.mean(p_vec - actuals)
        mae = np.mean(ae)
        rmse = np.sqrt(np.mean(se))

        # Paired tests vs Control
        d_ae = np.abs(preds_control - actuals) - ae
        d_se = (preds_control - actuals) ** 2 - se
        t_ae, p_ae = stats.ttest_1samp(d_ae, 0)
        t_se, p_se = stats.ttest_1samp(d_se, 0)

        results.append({
            "Model": name,
            "MAE": round(mae, 4),
            "RMSE": round(rmse, 4),
            "Bias": round(bias, 5),
            "MAE vs Control (diff)": round(d_ae.mean(), 5),
            "t-stat (vs Ctrl)": round(t_ae, 3),
            "p-value (vs Ctrl)": p_ae,
        })

    res_df = pd.DataFrame(results)
    print("\n" + "="*80)
    print("OUT-OF-SAMPLE EXPERIMENTAL RESULTS (1,000 CASES, 2026 SEASON)")
    print("="*80)
    print(res_df.to_string(index=False))

    # Also compare Upgrades directly against Shipped Base
    print("\n" + "="*80)
    print("HEAD-TO-HEAD VS SHIPPED BASE (k-NN)")
    print("="*80)
    base_ae = np.abs(preds_base - actuals)
    for name in ["Upgrade 1: VAA & Vertical Break", "Upgrade 2: Latent Embeddings (SVD)", "Upgrade 3: Pitch-by-Pitch Micro-Sim"]:
        p_vec = models[name]
        ae = np.abs(p_vec - actuals)
        diff = base_ae - ae
        t_stat, p_val = stats.ttest_1samp(diff, 0)
        print(f"{name:35s} | ΔMAE: {diff.mean():+.5f} | t: {t_stat:+.3f} | p-value: {p_val:.4e}")

if __name__ == "__main__":
    run_study()
