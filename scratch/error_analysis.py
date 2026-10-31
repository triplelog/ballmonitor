import numpy as np
import json
import csv
from ballmonitor.models.next_pitch.pitches import VOCAB, K

data = np.load("scratch/backtest_baseline.npz")
actuals = data["actuals"]
preds = data["preds"]
tree_preds = data["tree_preds"]
N = len(actuals)

with open("ballmonitor/models/next_pitch/data/backtest.csv") as f:
    rows = list(csv.DictReader(f))

# 1. Accuracy by count
counts = {}
for i, r in enumerate(rows):
    c = f"{r['balls']}-{r['strikes']}"
    counts.setdefault(c, []).append(i)

print("=== ACCURACY BY COUNT ===")
for c in sorted(counts.keys()):
    idxs = np.array(counts[c])
    y = actuals[idxs]
    p = preds[idxs]
    t = tree_preds[idxs]
    acc_gbm = (p.argmax(axis=1) == y).mean()
    acc_tree = (t.argmax(axis=1) == y).mean()
    print(f"Count {c:3s} ({len(idxs):3d} pitches): GBM={acc_gbm*100:5.1f}% | Tree={acc_tree*100:5.1f}%")

# 2. Confusion matrix and per-pitch-type recall/precision
print("\n=== ACCURACY BY PITCH TYPE ===")
y_pred = preds.argmax(axis=1)
for i, pt in enumerate(VOCAB):
    n_act = (actuals == i).sum()
    if n_act == 0:
        continue
    n_pred = (y_pred == i).sum()
    correct = ((y_pred == i) & (actuals == i)).sum()
    recall = correct / n_act if n_act > 0 else 0
    prec = correct / n_pred if n_pred > 0 else 0
    print(f"{pt:2s}: Actual={n_act:3d}, Pred={n_pred:3d}, Correct={correct:3d} | Recall={recall*100:5.1f}%, Prec={prec*100:5.1f}%")

# 3. Calibration: Expected Calibration Error (ECE)
print("\n=== CALIBRATION ANALYSIS ===")
top_probs = preds.max(axis=1)
top_correct = (y_pred == actuals).astype(float)
bins = np.linspace(0, 1, 11)
ece = 0.0
print("Confidence bin | Count | Mean Conf | Actual Acc | Diff")
for b_lo, b_hi in zip(bins[:-1], bins[1:]):
    mask = (top_probs >= b_lo) & (top_probs < b_hi)
    if mask.sum() > 0:
        conf = top_probs[mask].mean()
        acc = top_correct[mask].mean()
        diff = conf - acc
        ece += mask.sum() * abs(diff) / N
        print(f"[{b_lo:.1f}, {b_hi:.1f})      | {mask.sum():5d} | {conf*100:8.1f}% | {acc*100:9.1f}% | {diff*100:+5.1f}%")
print(f"Expected Calibration Error (ECE): {ece*100:.2f}%")
