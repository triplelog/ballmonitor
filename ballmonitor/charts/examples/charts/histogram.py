"""How a number is spread over player seasons, with a line at a value worked
out from all of them. Formulas over the columns of batting.csv (player,
year, team, league, born, G, AB, R, H, 2B, 3B, HR, RBI, SB, CS, BB, SO, HBP, SF).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/histogram.py --run histogram.png
    npx mathzetta-python examples/charts/histogram.py \
        keep='year >= 1950' value='SO / AB' marker='median(SO / AB)' --run strikeouts.png
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

# Which seasons to count.
# mathzetta: keep(data: columns) = AB >= 500
# The number to show the spread of.
# mathzetta: value(data: columns) = H / AB
# Where to draw the line: one number from the kept seasons (sum, mean, median, max …).
# mathzetta: marker(data: columns) = sum(H) / sum(AB)
# How many bars.
# mathzetta: bins(data: columns) = 40
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: its formula).
# mathzetta: x_label() = ""
# The y axis's name (empty: "seasons").
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
    values = per_row(value, rows)
    values = values[np.isfinite(values)]
    if not len(values):
        sys.exit(f"no seasons where {keep.formula}")
    line = float(marker(rows))

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    ax.hist(values, bins=int(bins(rows)), color="C0", edgecolor="white")
    ax.axvline(line, color="C3", linestyle="--", label=f"{label(marker)} = {line:.3g}")
    ax.set_xlabel(x_label() or label(value))
    ax.set_ylabel(y_label() or "seasons")
    ax.set_title(title() or f"{len(values)} seasons where {keep.formula}")
    ax.legend()
    fig.savefig(out, dpi=120)
    print(f"{out}: {len(values)} seasons, line at {line:.4g}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "histogram.png")
