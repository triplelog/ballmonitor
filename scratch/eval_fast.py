import csv
import json
import math
import time
import numpy as np
from pathlib import Path
from ballmonitor.core import registry
from ballmonitor.models.next_pitch.pitches import (
    VOCAB, INDEX, K, GBM_SPECS, LEVELS, load_history
)

m = registry.load_model("next_pitch")
data_dir = m.dir / "data"
meta = json.loads((data_dir / "meta.json").read_text())

with open(data_dir / "backtest.csv") as f:
    rows = list(csv.DictReader(f))

print(f"Loaded {len(rows)} backtest rows.")

# We will collect:
# - tree_logp: (N, K)
# - gbm_raw: (N, K)
# - actual_idx: (N,)
# using the exact logic of model.py!

t0 = time.time()
actuals = []
preds = []
tree_preds = []

# To measure exact model predictions:
for i, r in enumerate(rows):
    inputs, actual = m.backtest_case(r)
    pred = m.predict(inputs)
    actuals.append(INDEX[actual])
    preds.append([pred.extras["probs"][t] for t in VOCAB])
    tree_preds.append([pred.extras["tree_probs"][t] for t in VOCAB])
    if (i + 1) % 150 == 0:
        print(f"Row {i+1}/{len(rows)} in {time.time()-t0:.1f}s")

actuals = np.array(actuals)
preds = np.array(preds)
tree_preds = np.array(tree_preds)

# Calculate metrics
def calc_metrics(p, y):
    eps = 1e-12
    p_clipped = np.clip(p, eps, 1.0)
    # normalise
    p_norm = p_clipped / p_clipped.sum(axis=1, keepdims=True)
    nll = -np.log(p_norm[np.arange(len(y)), y])
    acc = (p_norm.argmax(axis=1) == y).mean()
    onehot = np.zeros_like(p_norm)
    onehot[np.arange(len(y)), y] = 1.0
    brier = ((p_norm - onehot) ** 2).sum(axis=1).mean()
    return acc, nll.mean(), nll.mean() / math.log(2), brier

acc, log_loss, bits, brier = calc_metrics(preds, actuals)
t_acc, t_log_loss, t_bits, t_brier = calc_metrics(tree_preds, actuals)

print("\n--- BASELINE RESULTS ---")
print(f"GBM (default):  acc={acc*100:.2f}%, log_loss={log_loss:.4f} nats ({bits:.4f} bits), brier={brier:.4f}")
print(f"Tree (default): acc={t_acc*100:.2f}%, log_loss={t_log_loss:.4f} nats ({t_bits:.4f} bits), brier={t_brier:.4f}")

np.savez("scratch/backtest_baseline.npz", actuals=actuals, preds=preds, tree_preds=tree_preds)
print("Saved baseline to scratch/backtest_baseline.npz")
