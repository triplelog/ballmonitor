"""A line a year, from that year's teams. Each point is a formula over whole
columns (sum, mean, max …) of the teams kept that year, from teams.csv
(year, team, league, name, AB, R, H, 2B, 3B, HR, BB, SO, SB, CS, HBP, SF:
each team's season batting totals).

From pyslots/ (or open it in the page: npm run serve):
    npx mathzetta-python examples/charts/trend.py --run trend.png
    npx mathzetta-python examples/charts/trend.py \
        keep='league = "AL"' per_year='sum(H) / sum(AB)' second='max(HR)' --run al.png
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.mathtext import MathTextParser

# mathzetta-data: ../data/teams.csv
# mathzetta-options: numpy

# Which teams count.
# mathzetta: keep(data: columns) = league = "AL" or league = "NL"
# One number a year from that year's teams.
# mathzetta: per_year(data: columns) = 1000 sum(HR) / sum(AB)
# A second line, on its own axis at the right.
# mathzetta: second(data: columns) = 1000 sum(SO) / sum(AB)
# The chart's title (empty: worked out from the formulas).
# mathzetta: title() = ""
# The x axis's name (empty: "year").
# mathzetta: x_label() = ""
# The y axis's name (empty: the first number's formula).
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
    years = np.unique(rows["year"])
    if not len(years):
        sys.exit(f"no teams where {keep.formula}")
    seasons = [select(rows, rows["year"] == year) for year in years]
    first = np.array([float(per_year(s)) for s in seasons])
    other = np.array([float(second(s)) for s in seasons])

    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    ax.plot(years, first, color="C0")
    ax.set_xlabel(x_label() or "year")
    ax.set_ylabel(y_label() or label(per_year), color="C0")
    right = ax.twinx()
    right.plot(years, other, color="C1")
    right.set_ylabel(label(second), color="C1")
    ax.set_title(title() or f"teams where {keep.formula}")
    fig.savefig(out, dpi=120)
    print(f"{out}: {len(years)} years, {int(years[0])}–{int(years[-1])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "trend.png")
