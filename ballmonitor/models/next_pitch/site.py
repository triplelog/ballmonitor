"""Public page: what each busy MLB pitcher is likely to throw in every count, and every
pitcher's 2026 pitch mix.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views next_pitch`); the page
only displays these numbers.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from collections import Counter

from ballmonitor.core import views as V
from ballmonitor.core.config import load_config
from ballmonitor.models.next_pitch.pitches import VOCAB

PLAIN = {
    "FF": "Four-seam fastball", "SI": "Sinker", "FC": "Cutter", "SL": "Slider", "ST": "Sweeper",
    "SV": "Slurve", "CU": "Curveball", "KC": "Knuckle curve", "CH": "Changeup", "FS": "Splitter",
    "FO": "Forkball", "KN": "Knuckleball", "EP": "Eephus", "SC": "Screwball",
}
# pitch families for the all-pitchers table
FAMILIES = [
    ("fastball", "Fastball / sinker", ("FF", "SI")),
    ("cutter", "Cutter", ("FC",)),
    ("slider", "Slider / sweeper", ("SL", "ST", "SV")),
    ("curve", "Curveball", ("CU", "KC", "SC", "EP")),
    ("change", "Changeup / splitter", ("CH", "FS", "FO", "KN")),
]
COUNTS = [(b, s) for b in range(4) for s in range(3)]
MAX_PITCH_COLUMNS = 6  # count column + 6 pitches = 7 columns


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _season_mix(path, season: str) -> Counter:
    mix: Counter = Counter()
    with gzip.open(path, "rt", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["date"].startswith(season) and r["pt"] in PLAIN:
                mix[r["pt"]] += 1
    return mix


def _site_model(model):
    """The same model with `method` set to site_method (the tree needs no optional dependency)."""
    method = model.params.site_method
    if model.params.method == method:
        return model
    return type(model)(load_config(model.dir, None, {"method": method}), model.dir)


def _by_last_name(name: str) -> str:
    parts = [w for w in name.split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return (parts[-1] if parts else name) + " " + name


def page(model) -> dict:
    p = model.params
    data = model.dir / "data"
    meta = json.loads((data / "meta.json").read_text())
    season = meta["last_date"][:4]
    with open(data / "pitchers.csv", newline="") as fh:
        pitchers = [r for r in csv.DictReader(fh) if int(r.get(f"pitches_{season}") or 0) > 0]
    pitchers.sort(key=lambda r: -int(r[f"pitches_{season}"]))
    hand = {"R": "RHP", "L": "LHP"}

    # every pitcher's real season mix (counted, not modelled)
    mix_rows = []
    for r in pitchers:
        n = int(r[f"pitches_{season}"])
        if n < p.site_mix_min_pitches:
            break
        mix = _season_mix(data / "pitchers" / f"{r['pitcher_id']}.csv.gz", season)
        total = sum(mix.values())
        if not total:
            continue
        row = {"pitcher": r["name"], "hand": hand.get(r["throws"], r["throws"]), "pitches": total}
        for key, _, codes in FAMILIES:
            row[key] = round(sum(mix[c] for c in codes) / total, 4)
        mix_rows.append(row)

    mix_table = V.table(
        "mix", f"Every pitcher's {season} pitch mix",
        [V.col("pitcher", "Pitcher"), V.col("hand", "Throws"), V.col("pitches", "Pitches", "int")]
        + [V.col(key, label, "pct", bar=True) for key, label, _ in FAMILIES],
        mix_rows, search=True, page_size=25, sort="pitches",
        subtitle=(f"Share of each pitcher's {season} pitches by type, for everyone who threw "
                  f"{p.site_mix_min_pitches:,.0f}+ pitches. Click a column to find who throws the most sliders."),
        note="Curveball includes knuckle curves and the odd eephus; changeup includes knuckleballs. "
             "Pitch types are MLB's Statcast labels.")

    # model: likely next pitch in every count, for the busiest pitchers
    m = _site_model(model)
    options = []
    for r in pitchers[: int(p.site_pitchers)]:
        grid = {}
        for stand in ("R", "L"):
            for b, s in COUNTS:
                pred = m.predict({"pitcher": r["pitcher_id"], "stand": stand, "balls": b, "strikes": s})
                grid[stand, b, s] = pred.extras["probs"]
        avg = {t: sum(g[t] for g in grid.values()) / len(grid) for t in VOCAB}
        shown = [t for t in sorted(VOCAB, key=lambda t: -avg[t]) if avg[t] >= 0.02][:MAX_PITCH_COLUMNS]
        mix = _season_mix(data / "pitchers" / f"{r['pitcher_id']}.csv.gz", season)
        total = sum(mix.values())
        views = [V.bar(
            f"mix_{r['pitcher_id']}", f"His {season} pitch mix",
            [{"label": PLAIN[t], "value": round(n / total, 4)} for t, n in mix.most_common() if n / total >= 0.01],
            fmt="pct", subtitle=f"All {total:,} pitches he threw in {season}.")]
        for stand, who in (("R", "right-handed"), ("L", "left-handed")):
            rows = []
            for b, s in COUNTS:
                probs = grid[stand, b, s]
                rows.append({"count": f"{b}-{s}", **{t: round(probs[t], 4) for t in shown}})
            views.append(V.table(
                f"counts_{stand}_{r['pitcher_id']}", f"Next pitch vs {who} hitters, by count",
                [V.col("count", "Count (balls-strikes)")] + [V.col(t, PLAIN[t], "pct", heat=True) for t in shown],
                rows, subtitle="Chance of each pitch in each count, not knowing what he threw the pitch before."))
        label = f"{r['name']} ({hand.get(r['throws'], r['throws'])})"
        options.append((_by_last_name(r["name"]), V.option(label, views)))
    options.sort(key=lambda o: o[0])
    picker = V.picker(
        "by_pitcher", "What will he throw next?", "Pitcher", [o for _, o in options],
        subtitle=(f"The {len(options)} pitchers who threw the most pitches in {season}, A to Z by last name. "
                  "Rows are counts (balls-strikes), from the first pitch (0-0) to a full count (3-2)."),
        note="Pitches he throws less than 2% of the time are left out, so a row can add up to a bit under 100%.",
        default=next((i for i, (_, o) in enumerate(options) if o["label"].startswith("Tarik Skubal")), 0))

    return V.page(
        title="What pitch is coming next?",
        summary=f"For {len(options)} MLB pitchers: the chance of a fastball, slider, changeup and more in every count.",
        sport="Baseball",
        updated=f"{season} season, final (pitches through {_day(meta['last_date'])})",
        how=("Every pitch a pitcher has thrown since 2021 is counted by count and by the hitter's side, with "
             "his latest games counting the most, and thin situations lean on his overall mix. Pitchers mix "
             "it up on purpose, so even the most likely pitch comes about half the time."),
        views=[picker, mix_table],
    )
