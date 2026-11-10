"""Pitcher seasons as a density map: hexagons coloured by how many seasons
(or how much of something) fall in each. Formulas over the columns of
pitching.csv (player, year, team, league, born, W, L, G, GS, SV, IPouts, H,
ER, HR, BB, SO: a row per season with 100 or more innings).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/pitchers.py --run pitchers.png
    npx mathzetta-python examples/charts/pitchers.py \
        x='27 BB / IPouts' y='27 SO / IPouts' weight='W' --run control.png
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.mathtext import MathTextParser

# mathzetta-data: ../data/pitching.csv
# mathzetta-options: numpy

# Which seasons to count.
# mathzetta: keep(data: columns) = year >= 1990
# What goes across: here strikeouts per nine innings.
# mathzetta: x(data: columns) = 27 SO / IPouts
# What goes up: here earned runs per nine innings (ERA).
# mathzetta: y(data: columns) = 27 ER / IPouts
# How much each season counts: 1 counts seasons; W adds up wins.
# mathzetta: weight(data: columns) = 1
# How many hexagons across.
# mathzetta: cells(data: columns) = 35
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: its formula).
# mathzetta: x_label() = ""
# The y axis's name (empty: its formula).
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
    xs, ys, weights = per_row(x, rows), per_row(y, rows), per_row(weight, rows)
    shown = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(weights)
    if not shown.any():
        sys.exit(f"no seasons where {keep.formula}")

    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    cells_ = ax.hexbin(xs[shown], ys[shown], C=weights[shown], reduce_C_function=np.sum,
                       gridsize=int(cells(rows)), cmap="magma_r", mincnt=1)
    fig.colorbar(cells_, label=label(weight) if weight.formula != "1" else "seasons")
    ax.set_xlabel(x_label() or label(x))
    ax.set_ylabel(y_label() or label(y))
    ax.set_title(title() or f"{shown.sum()} pitcher seasons where {keep.formula}")
    fig.savefig(out, dpi=120)
    print(f"{out}: {shown.sum()} of {count(table)} seasons")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pitchers.png")
