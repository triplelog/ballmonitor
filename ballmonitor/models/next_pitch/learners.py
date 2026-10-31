"""Learned challengers for the next_pitch study: gradient-boosted trees (LightGBM) and a small
sequence transformer (PyTorch). Both start from the context tree's log-probabilities and learn
corrections to it, so they can only add information on top of the simple model.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from ballmonitor.models.next_pitch import features as F

K = F.K
CONTEXT_COLS = ["balls", "strikes", "count", "outs_when_up", "inning", "on_1b", "on_2b", "on_3b", "score_diff",
                "n_thruorder_pitcher", "ab_idx", "game_pitch_n", "batters_faced", "pitcher_days_since_prev_game",
                "stand_i", "throws_i"]
SEQ_CAT = ["prev_t", "prev_r", "prev2_t", "prev2_r", "game_prev_t", "game_prev_r"]
SEQ_NUM = ["prev_x", "prev_z", "prev_speed", "prev_zone"]
BATTER_COLS = ["bat_pa", "bat_woba", "bat_k", "bat_bb", "bat_whiff", "bat_chase", "bat_slg",
               "bat_seen_fb", "bat_seen_br", "bat_seen_os"]


def feature_matrix(df: pd.DataFrame, rows: slice, counts: dict[str, np.ndarray], tree_logp: np.ndarray,
                   batter: pd.DataFrame) -> tuple[np.ndarray, list[str], list[str]]:
    """Dense float32 matrix for df rows `rows` (a contiguous slice). counts/tree_logp/batter are row-aligned with it."""
    sub = df.iloc[rows]
    n = len(sub)
    names = [f"tree_logp_{t}" for t in F.VOCAB]
    for spec in counts:
        names += [f"{spec}_share_{t}" for t in F.VOCAB] + [f"{spec}_logn"]
    names += CONTEXT_COLS + SEQ_CAT + SEQ_NUM + BATTER_COLS
    X = np.empty((n, len(names)), np.float32)
    X[:, :K] = tree_logp
    j = K
    for spec, c in counts.items():
        total = c.sum(axis=1, keepdims=True)
        X[:, j:j + K] = np.where(total > 0, c / np.maximum(total, 1e-9), np.nan)
        X[:, j + K] = np.log1p(total[:, 0])
        j += K + 1
    for col in CONTEXT_COLS + SEQ_CAT + SEQ_NUM:
        X[:, j] = sub[col].to_numpy(np.float32, na_value=np.nan)
        j += 1
    for col in BATTER_COLS:
        X[:, j] = batter[col].to_numpy(np.float32)
        j += 1
    return X, names, SEQ_CAT


GBM_PARAMS = {
    "objective": "multiclass", "num_class": K, "learning_rate": 0.08, "num_leaves": 63,
    "min_data_in_leaf": 400, "feature_fraction": 0.6, "bagging_fraction": 0.6, "bagging_freq": 1,
    "lambda_l2": 5.0, "max_bin": 63, "verbose": -1, "num_threads": 10, "seed": 7,
}


def train_gbm(X_tr, y_tr, init_tr, X_va, y_va, init_va, names, cats, log, max_rounds=1500):
    import lightgbm as lgb

    dtr = lgb.Dataset(X_tr, y_tr, init_score=init_tr.ravel(order="F"), feature_name=names,
                      categorical_feature=cats, free_raw_data=True)
    dva = lgb.Dataset(X_va, y_va, init_score=init_va.ravel(order="F"), reference=dtr)
    t = time.time()
    booster = lgb.train(GBM_PARAMS, dtr, max_rounds, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(100)])
    log(f"    GBM: {booster.best_iteration} rounds, {time.time() - t:.0f}s, valid loss {booster.best_score['valid_0']['multi_logloss']:.4f}")
    return booster


PER_PITCHER_PARAMS = {**{k: v for k, v in GBM_PARAMS.items()}, "num_leaves": 15, "min_data_in_leaf": 60,
                      "learning_rate": 0.05, "num_threads": 10}


def train_per_pitcher(X, y, logp, pitcher, train_end, cut, test_rows, min_train=1500):
    """One small boosted model per pitcher, trained only on that pitcher's pitches before the test season.

    Returns {pitcher: probs for that pitcher's test rows} for pitchers with >= min_train training pitches."""
    import lightgbm as lgb

    out = {}
    tr_p = pitcher[:train_end]
    test_p = pitcher[test_rows]
    for pid in np.unique(test_p):
        rows = np.flatnonzero(tr_p == pid)
        if len(rows) < min_train:
            continue
        fit, stop = rows[rows < cut], rows[rows >= cut]
        if len(stop) < 200 or len(fit) < 1000:
            continue
        dtr = lgb.Dataset(X[fit], y[fit], init_score=logp[fit].ravel(order="F"), free_raw_data=True)
        dva = lgb.Dataset(X[stop], y[stop], init_score=logp[stop].ravel(order="F"), reference=dtr)
        b = lgb.train(PER_PITCHER_PARAMS, dtr, 400, valid_sets=[dva], callbacks=[lgb.early_stopping(30, verbose=False)])
        sel = test_rows[test_p == pid]
        out[int(pid)] = (sel, gbm_predict(b, X[sel], logp[sel]).astype(np.float32))
    return out


def gbm_predict(booster, X, init) -> np.ndarray:
    raw = booster.predict(X, raw_score=True, num_iteration=booster.best_iteration) + init
    raw -= raw.max(axis=1, keepdims=True)
    p = np.exp(raw)
    return p / p.sum(axis=1, keepdims=True)


def gbm_importance(booster, names, top=25) -> list[tuple[str, float]]:
    gain = booster.feature_importance("gain")
    total = gain.sum() or 1.0
    order = np.argsort(-gain)[:top]
    return [(names[i], float(gain[i] / total)) for i in order]


# ── sequence transformer ─────────────────────────────────────────────────────

SEQ_LEN = 24  # previous pitches by this pitcher in this game


def game_sequences(df: pd.DataFrame, rows: slice) -> dict[str, np.ndarray]:
    """For each row, the previous SEQ_LEN pitches of the same pitcher in the same game (left padded)."""
    sub = df.iloc[rows]
    n = len(sub)
    # position of each pitch within its (game, pitcher) block, computed on the full frame order
    gp = sub["game_pitch_n"].to_numpy()
    tok_t = np.full((n, SEQ_LEN), F.NONE_TYPE + 1, np.int8)  # K+1 = padding
    tok_r = np.full((n, SEQ_LEN), F.NONE_RES + 1, np.int8)
    tok_num = np.zeros((n, SEQ_LEN, 5), np.float16)
    y = sub["y"].to_numpy()
    r = sub["res"].map({c: i for i, c in enumerate(F.RES_CODES)}).fillna(0).to_numpy()
    num = np.stack([
        sub["balls"].to_numpy(np.float32) / 3, sub["strikes"].to_numpy(np.float32) / 2,
        np.nan_to_num(sub["plate_x"].to_numpy(np.float32)), np.nan_to_num(sub["plate_z"].to_numpy(np.float32) - 2.5),
        (sub["ab_idx"].to_numpy() == 0).astype(np.float32),
    ], axis=1)
    # Rows of the same (game, pitcher) are not contiguous in the day-sorted frame, so map them.
    key = sub["game_pk"].to_numpy().astype(np.int64) * 10_000_000 + sub["pitcher"].to_numpy().astype(np.int64)
    order = np.lexsort((gp, key))
    sk, sg = key[order], gp[order]
    for lag in range(1, SEQ_LEN + 1):
        ok = np.zeros(n, bool)
        ok[lag:] = (sk[lag:] == sk[:-lag]) & (sg[lag:] - sg[:-lag] == lag)
        tgt = order[ok]
        src = order[np.flatnonzero(ok) - lag]
        tok_t[tgt, SEQ_LEN - lag] = y[src]
        tok_r[tgt, SEQ_LEN - lag] = r[src]
        tok_num[tgt, SEQ_LEN - lag] = num[src]
    return {"t": tok_t, "r": tok_r, "num": tok_num}


def _net(n_tab: int, d: int = 64, heads: int = 4, layers: int = 2):
    import torch
    from torch import nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb_t = nn.Embedding(K + 2, d)
            self.emb_r = nn.Embedding(F.NONE_RES + 2, d)
            self.num = nn.Linear(5, d)
            self.pos = nn.Parameter(torch.zeros(SEQ_LEN, d))
            layer = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout=0.1, batch_first=True)
            self.enc = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
            self.tab = nn.Sequential(nn.Linear(n_tab, 256), nn.GELU(), nn.Dropout(0.1), nn.Linear(256, d))
            self.query = nn.Parameter(torch.zeros(1, 1, d))
            self.head = nn.Sequential(nn.LayerNorm(2 * d), nn.Linear(2 * d, 128), nn.GELU(), nn.Linear(128, K))
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def forward(self, t, r, num, tab, base):
            pad = t == K + 1
            x = self.emb_t(t) + self.emb_r(r) + self.num(num) + self.pos
            q = self.tab(tab).unsqueeze(1) + self.query
            x = torch.cat([q, x], dim=1)
            mask = torch.cat([torch.zeros_like(pad[:, :1]), pad], dim=1)
            h = self.enc(x, src_key_padding_mask=mask)[:, 0]
            return base + self.head(torch.cat([h, q[:, 0]], dim=1))

    return Net()


def _tab_stats(X: np.ndarray, sample: int = 200_000, seed: int = 0):
    rng = np.random.default_rng(seed)
    S = np.nan_to_num(X[np.sort(rng.choice(len(X), min(sample, len(X)), replace=False))], nan=0.0)
    return S.mean(axis=0).astype(np.float32), (S.std(axis=0) + 1e-6).astype(np.float32)


def train_transformer(seq_tr, X_tr, y_tr, base_tr, seq_va, X_va, y_va, base_va, log, epochs=5, batch=2048, seed=7):
    """Rows are normalised batch by batch so the (large) training arrays can be views."""
    import torch

    torch.manual_seed(seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    mu, sd = _tab_stats(X_tr)
    net = _net(X_tr.shape[1]).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    steps = epochs * math.ceil(len(y_tr) / batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=steps)
    lossf = torch.nn.CrossEntropyLoss()

    def tensors(seq, X, base, sel):
        tab = (np.nan_to_num(X[sel], nan=0.0) - mu) / sd
        return (torch.from_numpy(seq["t"][sel]).to(device).long(), torch.from_numpy(seq["r"][sel]).to(device).long(),
                torch.from_numpy(seq["num"][sel]).to(device).float(), torch.from_numpy(tab.astype(np.float32)).to(device),
                torch.from_numpy(base[sel].astype(np.float32)).to(device))

    def evaluate(seq, X, base, y):
        net.eval()
        out = []
        with torch.no_grad():
            for s in range(0, len(base), 8192):
                sel = slice(s, s + 8192)
                out.append(torch.softmax(net(*tensors(seq, X, base, sel)), dim=1).cpu().numpy())
        net.train()
        p = np.concatenate(out)
        return p, float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1)).mean())

    rng = np.random.default_rng(seed)
    best, best_state = math.inf, None
    for ep in range(epochs):
        t = time.time()
        perm = rng.permutation(len(y_tr))
        for s in range(0, len(perm), batch):
            sel = np.sort(perm[s:s + batch])
            logits = net(*tensors(seq_tr, X_tr, base_tr, sel))
            loss = lossf(logits, torch.from_numpy(y_tr[sel].astype(np.int64)).to(device))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            sched.step()
        _, vloss = evaluate(seq_va, X_va, base_va, y_va)
        log(f"    transformer epoch {ep + 1}/{epochs}: valid loss {vloss:.4f} ({time.time() - t:.0f}s)")
        if vloss < best:
            best, best_state = vloss, {k: v.detach().clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)

    def predict(seq, X, base):
        return evaluate(seq, X, base, np.zeros(len(base), np.int64))[0]

    return predict
