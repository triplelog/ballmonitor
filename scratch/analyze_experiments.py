import numpy as np
import math

data = np.load("scratch/backtest_baseline.npz")
actuals = data["actuals"]
preds = data["preds"]
tree_preds = data["tree_preds"]
N, K = preds.shape

print(f"Loaded {N} cases.")

def score(p, y):
    eps = 1e-12
    p_norm = np.clip(p, eps, 1.0)
    p_norm /= p_norm.sum(axis=1, keepdims=True)
    nll = -np.log(p_norm[np.arange(len(y)), y])
    acc = (p_norm.argmax(axis=1) == y).mean()
    onehot = np.zeros_like(p_norm)
    onehot[np.arange(len(y)), y] = 1.0
    brier = ((p_norm - onehot) ** 2).sum(axis=1).mean()
    return acc, nll.mean(), nll.mean() / math.log(2), brier

acc_gbm, loss_gbm, bits_gbm, brier_gbm = score(preds, actuals)
acc_tree, loss_tree, bits_tree, brier_tree = score(tree_preds, actuals)

print(f"Baseline GBM:  Acc={acc_gbm*100:.2f}%, LogLoss={loss_gbm:.4f} nats ({bits_gbm:.4f} bits), Brier={brier_gbm:.4f}")
print(f"Baseline Tree: Acc={acc_tree*100:.2f}%, LogLoss={loss_tree:.4f} nats ({bits_tree:.4f} bits), Brier={brier_tree:.4f}")

# 1. Temperature scaling on GBM
print("\n--- Temperature scaling on GBM ---")
best_temp = 1.0
best_bits = bits_gbm
for t in np.arange(0.5, 2.01, 0.05):
    logits = np.log(np.clip(preds, 1e-12, 1.0)) / t
    logits -= logits.max(axis=1, keepdims=True)
    p_t = np.exp(logits)
    p_t /= p_t.sum(axis=1, keepdims=True)
    a, l, b, br = score(p_t, actuals)
    if b < best_bits:
        best_bits = b
        best_temp = t
    if abs(t - round(t, 1)) < 1e-4 and round(t, 1) in [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]:
        print(f"  T={t:.2f}: Acc={a*100:.2f}%, Bits={b:.4f}, Brier={br:.4f}")
print(f"Optimal Temperature: {best_temp:.2f} -> Bits={best_bits:.4f} (delta: {best_bits - bits_gbm:+.4f})")

# 2. Probability Blending: alpha * GBM + (1 - alpha) * Tree
print("\n--- Probability blending: alpha * GBM + (1 - alpha) * Tree ---")
best_alpha = 1.0
best_blend_bits = bits_gbm
for alpha in np.arange(0.0, 1.01, 0.05):
    blend = alpha * preds + (1.0 - alpha) * tree_preds
    a, l, b, br = score(blend, actuals)
    if b < best_blend_bits:
        best_blend_bits = b
        best_alpha = alpha
    if abs(alpha - round(alpha, 1)) < 1e-4 and round(alpha, 1) in [0.0, 0.5, 0.7, 0.8, 0.9, 1.0]:
        print(f"  alpha={alpha:.2f}: Acc={a*100:.2f}%, Bits={b:.4f}, Brier={br:.4f}")
print(f"Optimal Alpha: {best_alpha:.2f} -> Bits={best_blend_bits:.4f} (delta: {best_blend_bits - bits_gbm:+.4f})")

# 3. Geometric / Logit blend: logit_blend = alpha * log(GBM) + (1 - alpha) * log(Tree)
print("\n--- Geometric / Logit blending ---")
for alpha in [0.7, 0.8, 0.85, 0.9, 0.95, 1.0]:
    log_p = alpha * np.log(np.clip(preds, 1e-12, 1.0)) + (1.0 - alpha) * np.log(np.clip(tree_preds, 1e-12, 1.0))
    log_p -= log_p.max(axis=1, keepdims=True)
    p_geom = np.exp(log_p)
    p_geom /= p_geom.sum(axis=1, keepdims=True)
    a, l, b, br = score(p_geom, actuals)
    print(f"  alpha={alpha:.2f}: Acc={a*100:.2f}%, Bits={b:.4f}, Brier={br:.4f}")
