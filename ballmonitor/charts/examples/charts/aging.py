"""One number for each age: the seasons of that age grouped, and a formula
over the group (sum, mean, median …) for each, with the number of seasons
underneath. From batting.csv (player, year, team, league, born, G, AB, R, H,
2B, 3B, HR, RBI, SB, CS, BB, SO, HBP, SF).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/aging.py --run aging.png
    npx mathzetta-python examples/charts/aging.py per_age='1000 sum(HR) / sum(AB)' --run power.png
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
# mathzetta: keep(data: columns) = year >= 1954
# Each season's place along the bottom: here the player's age that year.
# mathzetta: age(data: columns) = year - born
# The number for each age, from all its seasons together: here on-base percentage.
# mathzetta: per_age(data: columns) = sum(H + BB + HBP) / sum(AB + BB + HBP + SF)
# Ages with fewer seasons than this are left out.
# mathzetta: fewest(data: columns) = 30
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: the age's formula).
# mathzetta: x_label() = ""
# The y axis's name (empty: the formula over each age).
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
    ages = per_row(age, rows)
    known = np.isfinite(ages)
    smallest = int(fewest(rows))
    xs, ys, ns = [], [], []
    for a in np.unique(ages[known]):
        group = select(rows, ages == a)
        if count(group) >= smallest:
            xs.append(a)
            ys.append(float(per_age(group)))
            ns.append(count(group))
    if not xs:
        sys.exit(f"no age has {smallest} seasons where {keep.formula}")

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(8, 6), sharex=True, height_ratios=[3, 1], layout="constrained")
    top.plot(xs, ys, marker="o", color="C0")
    top.set_ylabel(y_label() or label(per_age))
    top.set_title(title() or f"seasons where {keep.formula}")
    bottom.bar(xs, ns, color="C7")
    bottom.set_ylabel("seasons")
    bottom.set_xlabel(x_label() or label(age))
    fig.savefig(out, dpi=120)
    best = xs[int(np.argmax(ys))]
    print(f"{out}: {len(xs)} ages; highest at {best:g} ({max(ys):.4g})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "aging.png")
