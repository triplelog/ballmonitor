"""The best player seasons by a score, as bars. Formulas over the columns
of batting.csv (player, year, team, league, born, G, AB, R, H, 2B, 3B, HR, RBI,
SB, CS, BB, SO, HBP, SF). The default score ranks power and speed together:
a season's smaller of home runs and stolen bases.

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/top.py --run top.png
    npx mathzetta-python examples/charts/top.py \
        keep='year >= 1951 and SB + CS >= 40' score='SB / (SB + CS)' how_many=20 --run steals.png
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.mathtext import MathTextParser

# mathzetta-data: ../data/batting.csv
# mathzetta-options: numpy

# Which seasons may be ranked.
# mathzetta: keep(data: columns) = year >= 1901
# What to rank them by, highest first.
# mathzetta: score(data: columns) = min(HR, SB)
# How many bars.
# mathzetta: how_many(data: columns) = 15
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: the score's formula).
# mathzetta: x_label() = ""
# The y axis's name (empty: no name).
# mathzetta: y_label() = ""


def load_csv(path):
    """The table as {column: numpy array}: numbers where every value is one, else text."""
    with open(path, newline="", encoding="utf-8") as f:
        header, *rows = list(csv.reader(f))
    table = {}
    for i, name in enumerate(header):
        values = [row[i] for row in rows]
        try:
            table[name] = np.array([float(v) if v else np.nan for v in values])
        except ValueError:
            table[name] = np.array(values)
    return table


def count(table):
    return len(next(iter(table.values())))


def select(table, mask):
    """The rows where mask is true (one True or False: all rows or none)."""
    mask = np.broadcast_to(np.asarray(mask, dtype=bool), (count(table),))
    return {name: column[mask] for name, column in table.items()}


def per_row(fn, table):
    """fn over the table, one value a row (a formula like `2` gives every row the same)."""
    return np.broadcast_to(fn(table), (count(table),))


def label(fn):
    """A filled formula as maths if matplotlib can draw it, else as typed."""
    try:
        MathTextParser("path").parse(f"${fn.latex}$")
        return f"${fn.latex}$"
    except Exception:
        return fn.formula


def main(out):
    table = load_csv(DATA_FILE)
    rows = select(table, keep(table))
    scores = per_row(score, rows)
    ranked = [i for i in np.argsort(-scores, kind="stable") if np.isfinite(scores[i])][: int(how_many(rows))]
    if not ranked:
        sys.exit(f"no seasons where {keep.formula}")
    names = [f'{rows["player"][i]} {int(rows["year"][i])} ({rows["team"][i]})' for i in ranked]

    fig, ax = plt.subplots(figsize=(8, 0.35 * len(ranked) + 1.5), layout="constrained")
    ax.barh(names[::-1], scores[ranked][::-1], color="C2")
    ax.set_xlabel(x_label() or label(score))
    ax.set_ylabel(y_label())
    ax.set_title(title() or f"top {len(ranked)} seasons where {keep.formula}")
    fig.savefig(out, dpi=120)
    print(f"{out}: " + "; ".join(f"{n} {scores[i]:.4g}" for n, i in zip(names[:3], ranked)) + " …")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "top.png")
