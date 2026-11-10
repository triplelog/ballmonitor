"""Player seasons as a scatter chart. Which seasons, what goes on each axis,
the colour and the x axis's range are formulas over the columns of
batting.csv (player, year, team, league, born, G, AB, R, H, 2B, 3B, HR, RBI, SB,
CS, BB, SO, HBP, SF: a row per season with 400 or more at bats).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/scatter.py --run scatter.png
    npx mathzetta-python examples/charts/scatter.py \
        keep='year >= 2000' x='(H + BB + HBP) / (AB + BB + HBP + SF)' \
        y='(H + 2B + 2*3B + 3 HR) / AB' --run obp-slg.png
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

# Which seasons to plot: true or false for each row.
# mathzetta: keep(data: columns) = year >= 1990
# What goes across.
# mathzetta: x(data: columns) = HR
# What goes up.
# mathzetta: y(data: columns) = H / AB
# Each point's colour.
# mathzetta: shade(data: columns) = year
# The x axis's range [from, to], worked out from the plotted seasons.
# mathzetta: x_range(data: columns) = [0, 1.05 max(x(data))]
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
    xs, ys, colours = per_row(x, rows), per_row(y, rows), per_row(shade, rows)
    shown = np.isfinite(xs) & np.isfinite(ys)
    if not shown.any():
        sys.exit(f"no seasons where {keep.formula}")

    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    points = ax.scatter(xs[shown], ys[shown], c=colours[shown], s=10, alpha=0.6, cmap="viridis")
    fig.colorbar(points, label=label(shade))
    ax.set_xlabel(x_label() or label(x))
    ax.set_ylabel(y_label() or label(y))
    ax.set_xlim(*x_range(select(rows, shown)))
    ax.set_title(title() or f"{shown.sum()} seasons where {keep.formula}")
    fig.savefig(out, dpi=120)
    print(f"{out}: {shown.sum()} of {count(table)} seasons")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scatter.png")
