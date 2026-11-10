"""Player seasons in groups, a box for each: the middle half of the values,
the median, and the spread. Which seasons, how they are grouped and the value
are formulas over the columns of batting.csv (player, year, team, league,
born, G, AB, R, H, 2B, 3B, HR, RBI, SB, CS, BB, SO, HBP, SF).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/boxplot.py --run boxplot.png
    npx mathzetta-python examples/charts/boxplot.py \
        group='year - born' value='(H + BB + HBP) / (AB + BB + HBP + SF)' keep='year >= 1954' --run ages.png
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
# mathzetta: keep(data: columns) = year >= 1920
# The group each season goes in: one box per value (a decade, an age, a league …).
# mathzetta: group(data: columns) = 10 floor(year / 10)
# The number whose spread each box shows.
# mathzetta: value(data: columns) = HR / AB
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: the group's formula).
# mathzetta: x_label() = ""
# The y axis's name (empty: the value's formula).
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
    groups, values = per_row(group, rows), per_row(value, rows)
    shown = np.isfinite(values) & (groups == groups)   # a missing group (nan) is no group
    if not shown.any():
        sys.exit(f"no seasons where {keep.formula}")
    names = np.unique(groups[shown])
    boxes = [values[shown & (groups == g)] for g in names]

    fig, ax = plt.subplots(figsize=(max(6, 0.45 * len(names) + 2), 5), layout="constrained")
    ax.boxplot(boxes, tick_labels=[f"{g:g}" if isinstance(g, float) else str(g) for g in names], showfliers=False)
    ax.set_xlabel(x_label() or label(group))
    ax.set_ylabel(y_label() or label(value))
    ax.tick_params(axis="x", labelrotation=45 if len(names) > 12 else 0)
    ax.set_title(title() or f"{shown.sum()} seasons where {keep.formula}")
    fig.savefig(out, dpi=120)
    print(f"{out}: {len(names)} groups, {shown.sum()} seasons")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "boxplot.png")
